"""
batch_eval_app.py — Batch evaluation on a dataset folder (train / val splits).

Folder structure expected (any of these work):
  dataset/
    train/images/   +  train/labels/   ← YOLO standard
    val/images/    +  val/labels/
  — or —
  dataset/
    train/   ← images + .txt labels side-by-side
    val/

If label (.txt) files are found, accuracy metrics are computed automatically:
  • Count Accuracy %  (images where pred_count == gt_count, per class)
  • MAE              (mean |pred − gt| per class)
  • Over / Under      (avg diff, positive = over-detect)

If no label files, the app still works as a pure detection counter.
"""

import csv
import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QProgressBar, QPushButton, QSlider,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QMessageBox,
    QSplitter,
)


IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif'}


def _get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


DEFAULT_MODEL = str(_get_base_dir() / 'ai_3g_v7.pt')


# ── dataset helpers ──────────────────────────────────────────────────────────

def collect_images(folder: Path) -> list[tuple[str, Path]]:
    """Return [(split, image_path), …] scanning train/ and val/ first."""
    results: list[tuple[str, Path]] = []
    for split in ('train', 'val'):
        # support both  dataset/train/*.jpg  and  dataset/train/images/*.jpg
        for sub in (folder / split, folder / split / 'images'):
            if sub.is_dir():
                for p in sorted(sub.rglob('*')):
                    if p.is_file() and p.suffix.lower() in IMG_EXTS:
                        results.append((split, p))
                break  # prefer 'images' sub if found, else plain train/
    if not results:
        for p in sorted(folder.rglob('*')):
            if p.is_file() and p.suffix.lower() in IMG_EXTS:
                results.append(('root', p))
    return results


def find_label_file(image_path: Path) -> Path | None:
    """Locate the YOLO .txt label file for an image.

    Checks (in order):
      1. same directory, same stem
      2. ../labels/<stem>.txt          (flat: train/labels/)
      3. replace 'images' segment with 'labels' in path
    """
    stem = image_path.stem

    # 1 — side-by-side
    candidate = image_path.parent / f"{stem}.txt"
    if candidate.exists():
        return candidate

    # 2 — sibling labels/ folder
    candidate = image_path.parent.parent / 'labels' / image_path.parent.name / f"{stem}.txt"
    if candidate.exists():
        return candidate

    # 3 — replace 'images' segment anywhere in the path
    parts = list(image_path.parts)
    for i, part in enumerate(parts):
        if part.lower() == 'images':
            new_parts = parts[:i] + ['labels'] + parts[i+1:]
            candidate = Path(*new_parts).parent / f"{stem}.txt"
            if candidate.exists():
                return candidate

    return None


def read_gt_counts(label_path: Path, id_to_name: dict[int, str]) -> dict[str, int]:
    """Parse a YOLO label file and return {class_name: count}."""
    counts: dict[str, int] = {}
    try:
        for line in label_path.read_text(encoding='utf-8').splitlines():
            parts = line.strip().split()
            if parts:
                cls_id = int(parts[0])
                name = id_to_name.get(cls_id, f"class_{cls_id}")
                counts[name] = counts.get(name, 0) + 1
    except Exception:
        pass
    return counts


# ── background workers ───────────────────────────────────────────────────────

class ModelLoader(QThread):
    ready  = pyqtSignal(object, str)
    status = pyqtSignal(str, str)

    def __init__(self, model_path: str):
        super().__init__()
        self.model_path = model_path

    def run(self):
        self.status.emit("กำลังโหลด model…", "#FF9800")
        pt = Path(self.model_path)
        ov = pt.parent / (pt.stem + '_openvino_model')

        if pt.suffix == '.pt' and not ov.exists():
            self.status.emit("Export → OpenVINO…", "#FF9800")
            try:
                tmp = YOLO(str(pt))
                tmp.export(format='openvino', half=False)
                del tmp
            except Exception as e:
                self.status.emit(f"Export ล้มเหลว: {e}", "#EF9A9A")

        if ov.exists():
            try:
                model = YOLO(str(ov), task='obb')
                name  = f"{ov.name}  [OpenVINO]"
            except Exception:
                model = YOLO(self.model_path, task='obb')
                name  = f"{pt.name}  [.pt fallback]"
        else:
            model = YOLO(self.model_path, task='obb')
            name  = f"{pt.name}  [.pt]"

        self.ready.emit(model, name)


class BatchWorker(QThread):
    # split, filename, pred_counts, gt_counts, latency_ms, has_labels
    image_done = pyqtSignal(str, str, dict, dict, float, bool)
    all_done   = pyqtSignal()
    error      = pyqtSignal(str, str)

    def __init__(self, model, images: list[tuple[str, Path]],
                 conf: float, id_to_name: dict[int, str]):
        super().__init__()
        self.model      = model
        self.images     = images
        self.conf       = conf
        self.id_to_name = id_to_name
        self._stop      = False

    def stop(self):
        self._stop = True

    def run(self):
        for split, path in self.images:
            if self._stop:
                break
            try:
                buf   = np.fromfile(str(path), dtype=np.uint8)
                frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                if frame is None:
                    self.error.emit(path.name, "อ่านภาพไม่ได้")
                    continue

                t0  = time.perf_counter()
                res = self.model(frame, conf=self.conf, verbose=False)[0]
                ms  = (time.perf_counter() - t0) * 1000

                pred: dict[str, int] = {}
                boxes = res.obb if res.obb is not None and len(res.obb) > 0 else None
                if boxes is not None:
                    for idx in boxes.cls.tolist():
                        n = self.model.names[int(idx)]
                        pred[n] = pred.get(n, 0) + 1

                lf = find_label_file(path)
                if lf:
                    gt = read_gt_counts(lf, self.id_to_name)
                    has_labels = True
                else:
                    gt = {}
                    has_labels = False

                self.image_done.emit(split, path.name, pred, gt, ms, has_labels)

            except Exception as e:
                traceback.print_exc()
                self.error.emit(path.name, f"{type(e).__name__}: {e}")

        self.all_done.emit()


# ── drop-zone ─────────────────────────────────────────────────────────────────

class FolderDropZone(QLabel):
    folder_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(80)
        self._idle()

    def _idle(self):
        self.setText("วาง  dataset folder  ที่นี่\nหรือกดปุ่ม  Select Folder")
        self.setStyleSheet(
            "background:#1a1a2e; color:#555; font-size:15px;"
            "border:2px dashed #444; border-radius:10px;"
        )

    def set_folder(self, path: str):
        self.setText(f"📁  {path}")
        self.setStyleSheet(
            "background:#0d2137; color:#90CAF9; font-size:12px;"
            "border:2px solid #1565C0; border-radius:10px; padding:6px;"
        )

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        for u in e.mimeData().urls():
            p = Path(u.toLocalFile())
            if p.is_dir():
                self.folder_dropped.emit(str(p))
                return


# ── main window ───────────────────────────────────────────────────────────────

class BatchEvalWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Batch Evaluation — Dataset Folder")
        self.resize(1500, 860)

        self._model      = None
        self._model_name = "—"
        self._conf       = 0.50
        self._images:    list[tuple[str, Path]] = []
        # (split, filename, pred_counts, gt_counts, ms, has_labels)
        self._results:   list[tuple] = []
        self._worker:    BatchWorker | None = None
        self._loader:    ModelLoader | None = None
        self._has_any_labels = False

        self._build_ui()
        self._load_model(DEFAULT_MODEL)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # status bar
        self.lbl_status = QLabel("กำลังโหลด model…")
        self.lbl_status.setFixedHeight(32)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet(
            "font-size:13px; font-weight:bold; color:#FF9800;"
            "background:#1e1e2e; border-radius:6px; padding:4px;"
        )
        root.addWidget(self.lbl_status)

        # top controls row
        top = QHBoxLayout()
        top.setSpacing(8)

        # folder drop-zone
        folder_box = QGroupBox("Dataset Folder")
        folder_lay = QVBoxLayout(folder_box)
        self.drop_zone = FolderDropZone()
        self.drop_zone.folder_dropped.connect(self._on_folder_selected)
        folder_lay.addWidget(self.drop_zone)
        btn_sel = QPushButton("Select Folder…")
        btn_sel.setFixedHeight(30)
        btn_sel.clicked.connect(self._pick_folder)
        folder_lay.addWidget(btn_sel)
        self.lbl_img_count = QLabel("รูปทั้งหมด: —")
        self.lbl_img_count.setStyleSheet("color:#E0E0E0; font-size:12px;")
        folder_lay.addWidget(self.lbl_img_count)
        top.addWidget(folder_box, 3)

        # model + conf + run
        ctrl_box = QGroupBox("Controls")
        ctrl_lay = QVBoxLayout(ctrl_box)

        btn_model = QPushButton("เลือก model (.pt / .xml)")
        btn_model.setFixedHeight(28)
        btn_model.clicked.connect(self._pick_model)
        ctrl_lay.addWidget(btn_model)

        self.lbl_model = QLabel("—")
        self.lbl_model.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_model.setStyleSheet("color:#90CAF9; font-size:11px;")
        ctrl_lay.addWidget(self.lbl_model)

        ctrl_lay.addSpacing(4)

        # confidence slider
        self.lbl_conf = QLabel(f"Confidence Threshold:  {self._conf:.2f}")
        self.lbl_conf.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_conf.setStyleSheet(
            "font-size:14px; font-weight:bold; color:#FFD54F;"
            "background:#2a2a1a; border-radius:5px; padding:3px;"
        )
        ctrl_lay.addWidget(self.lbl_conf)

        self.slider_conf = QSlider(Qt.Orientation.Horizontal)
        self.slider_conf.setRange(1, 99)
        self.slider_conf.setValue(int(self._conf * 100))
        self.slider_conf.setTickInterval(10)
        self.slider_conf.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_conf.valueChanged.connect(self._on_conf_changed)
        ctrl_lay.addWidget(self.slider_conf)

        ctrl_lay.addSpacing(6)

        self.btn_run = QPushButton("▶  Run All")
        self.btn_run.setFixedHeight(38)
        self.btn_run.setStyleSheet(
            "font-size:15px; font-weight:bold; background:#1B5E20; color:white;"
        )
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._run_all)
        ctrl_lay.addWidget(self.btn_run)

        self.btn_stop = QPushButton("⏹  Stop")
        self.btn_stop.setFixedHeight(28)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        ctrl_lay.addWidget(self.btn_stop)

        btn_export = QPushButton("Export CSV…")
        btn_export.setFixedHeight(28)
        btn_export.clicked.connect(self._export_csv)
        ctrl_lay.addWidget(btn_export)

        top.addWidget(ctrl_box, 1)
        root.addLayout(top)

        # progress bar
        self.progress = QProgressBar()
        self.progress.setFixedHeight(20)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        # splitter: detail table | accuracy / summary table
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── detail table ──────────────────────────────────────────────────────
        detail_box = QGroupBox("ผลลัพธ์รายภาพ")
        detail_lay = QVBoxLayout(detail_box)

        self.detail_table = QTableWidget(0, 7)
        self.detail_table.setHorizontalHeaderLabels(
            ["Split", "Filename", "Class",
             "GT", "Pred", "Diff", "Latency (ms)"]
        )
        hh = self.detail_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col, w in zip((0, 3, 4, 5, 6), (55, 50, 55, 55, 95)):
            self.detail_table.setColumnWidth(col, w)
        self.detail_table.setFont(QFont("Arial", 11))
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_table.verticalHeader().setDefaultSectionSize(26)
        detail_lay.addWidget(self.detail_table)
        splitter.addWidget(detail_box)

        # ── accuracy / summary table ──────────────────────────────────────────
        acc_box = QGroupBox("Accuracy & สรุป  (ต้องมี label .txt)")
        acc_lay = QVBoxLayout(acc_box)

        self.lbl_overall = QLabel("ยังไม่มีข้อมูล")
        self.lbl_overall.setWordWrap(True)
        self.lbl_overall.setStyleSheet(
            "color:#E0E0E0; font-size:12px;"
            "background:#1a2a1a; border-radius:5px; padding:5px;"
        )
        acc_lay.addWidget(self.lbl_overall)

        self.acc_table = QTableWidget(0, 7)
        self.acc_table.setHorizontalHeaderLabels([
            "Split", "Class",
            "GT Total", "Pred Total",
            "MAE", "Count Acc %", "Avg Diff"
        ])
        sh = self.acc_table.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        sh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, w in zip((0, 2, 3, 4, 5, 6), (55, 80, 80, 60, 90, 70)):
            self.acc_table.setColumnWidth(col, w)
        self.acc_table.setFont(QFont("Arial", 11))
        self.acc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.acc_table.verticalHeader().setDefaultSectionSize(26)
        acc_lay.addWidget(self.acc_table)

        # legend
        legend = QLabel(
            "GT = Ground Truth จาก label file  |  "
            "MAE = ค่าเฉลี่ย |pred − gt|  |  "
            "Count Acc = % รูปที่ pred == gt  |  "
            "Avg Diff > 0 = over-detect,  < 0 = under-detect"
        )
        legend.setWordWrap(True)
        legend.setStyleSheet("color:#777; font-size:10px;")
        acc_lay.addWidget(legend)

        splitter.addWidget(acc_box)
        splitter.setSizes([820, 580])
        root.addWidget(splitter, 1)

    # ── model ─────────────────────────────────────────────────────────────────

    def _load_model(self, path: str):
        self._model = None
        self._loader = ModelLoader(path)
        self._loader.status.connect(self._on_status)
        self._loader.ready.connect(self._on_model_ready)
        self._loader.start()

    def _on_model_ready(self, model, name: str):
        self._model      = model
        self._model_name = name
        self.lbl_model.setText(name)
        self._on_status(f"Model พร้อม  —  {name}", "#4CAF50")
        self._refresh_run_btn()

    def _pick_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "เลือก model", str(_get_base_dir()),
            "Model files (*.pt *.xml);;All files (*.*)"
        )
        if not path:
            return
        p = Path(path)
        self._load_model(str(p.parent) if p.suffix == '.xml' else path)

    # ── confidence ────────────────────────────────────────────────────────────

    def _on_conf_changed(self, val: int):
        self._conf = val / 100.0
        self.lbl_conf.setText(f"Confidence Threshold:  {self._conf:.2f}")

    # ── folder ────────────────────────────────────────────────────────────────

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "เลือก dataset folder", str(_get_base_dir())
        )
        if folder:
            self._on_folder_selected(folder)

    def _on_folder_selected(self, folder: str):
        self.drop_zone.set_folder(folder)
        self._images = collect_images(Path(folder))
        splits: dict[str, int] = {}
        for s, _ in self._images:
            splits[s] = splits.get(s, 0) + 1
        parts = [f"{s}: {n}" for s, n in sorted(splits.items())]
        self.lbl_img_count.setText(
            f"รูปทั้งหมด: {len(self._images)}  ({',  '.join(parts)})"
        )
        self.progress.setValue(0)
        self.progress.setMaximum(max(len(self._images), 1))
        self._refresh_run_btn()

    # ── run ───────────────────────────────────────────────────────────────────

    def _refresh_run_btn(self):
        self.btn_run.setEnabled(bool(self._model and self._images))

    def _run_all(self):
        if not self._model or not self._images:
            return

        self._results = []
        self._has_any_labels = False
        self.detail_table.setRowCount(0)
        self.acc_table.setRowCount(0)
        self.lbl_overall.setText("กำลังรัน…")
        self.progress.setValue(0)
        self.progress.setMaximum(len(self._images))

        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._on_status(f"กำลังรัน  0 / {len(self._images)}…", "#FF9800")

        id_to_name = {v: k for k, v in
                      {name: idx for idx, name in self._model.names.items()}.items()}
        # simpler: model.names is already {int: str}
        id_to_name = dict(self._model.names)

        self._worker = BatchWorker(
            self._model, self._images, self._conf, id_to_name
        )
        self._worker.image_done.connect(self._on_image_done)
        self._worker.error.connect(self._on_image_error)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.stop()
        self.btn_stop.setEnabled(False)
        self._on_status("กำลังหยุด…", "#FF9800")

    def _on_image_done(self, split: str, filename: str,
                       pred: dict, gt: dict, ms: float, has_labels: bool):
        self._results.append((split, filename, pred, gt, ms, has_labels))
        if has_labels:
            self._has_any_labels = True
        done = len(self._results)
        total = len(self._images)
        self.progress.setValue(done)
        self._on_status(f"กำลังรัน  {done} / {total}…", "#FF9800")
        self._add_detail_rows(split, filename, pred, gt, ms, has_labels)

    def _on_image_error(self, filename: str, msg: str):
        self._results.append(('error', filename, {}, {}, 0.0, False))
        r = self.detail_table.rowCount()
        self.detail_table.insertRow(r)
        self.detail_table.setItem(r, 0, _cell("err"))
        self.detail_table.setItem(r, 1, _cell(filename))
        err = _cell(f"ERROR: {msg}")
        err.setForeground(Qt.GlobalColor.red)
        self.detail_table.setItem(r, 2, err)

    def _on_all_done(self):
        self.btn_stop.setEnabled(False)
        self.btn_run.setEnabled(bool(self._model and self._images))
        n_ok   = sum(1 for r in self._results if r[0] != 'error')
        t_obj  = sum(sum(r[2].values()) for r in self._results)
        avg_ms = (
            sum(r[4] for r in self._results if r[4] > 0) /
            max(1, sum(1 for r in self._results if r[4] > 0))
        )
        self._on_status(
            f"เสร็จ  {n_ok} รูป  |  Objects รวม: {t_obj}"
            f"  |  Avg latency: {avg_ms:.1f} ms"
            f"  |  conf = {self._conf:.2f}",
            "#4CAF50",
        )
        self._build_accuracy_table()

    # ── detail rows ───────────────────────────────────────────────────────────

    def _add_detail_rows(self, split: str, filename: str,
                         pred: dict, gt: dict, ms: float, has_labels: bool):
        all_classes = sorted(set(list(pred.keys()) + list(gt.keys())))
        if not all_classes:
            r = self.detail_table.rowCount()
            self.detail_table.insertRow(r)
            self.detail_table.setItem(r, 0, _cell(split))
            self.detail_table.setItem(r, 1, _cell(filename))
            self.detail_table.setItem(r, 2, _cell("—"))
            self.detail_table.setItem(r, 3, _cell("0" if has_labels else "—", center=True))
            self.detail_table.setItem(r, 4, _cell("0", center=True))
            self.detail_table.setItem(r, 5, _cell("0" if has_labels else "—", center=True))
            self.detail_table.setItem(r, 6, _cell(f"{ms:.1f}", center=True))
            return

        first = True
        for cls in all_classes:
            p = pred.get(cls, 0)
            g = gt.get(cls, 0) if has_labels else None
            diff = (p - g) if g is not None else None

            r = self.detail_table.rowCount()
            self.detail_table.insertRow(r)
            self.detail_table.setItem(r, 0, _cell(split if first else ""))
            self.detail_table.setItem(r, 1, _cell(filename if first else ""))
            self.detail_table.setItem(r, 2, _cell(cls))
            self.detail_table.setItem(r, 3, _cell(str(g) if g is not None else "—", center=True))
            self.detail_table.setItem(r, 4, _cell(str(p), center=True))

            if diff is not None:
                diff_item = _cell(f"{diff:+d}", center=True)
                if diff > 0:
                    diff_item.setForeground(Qt.GlobalColor.yellow)   # over
                elif diff < 0:
                    diff_item.setForeground(Qt.GlobalColor.red)      # under
                else:
                    diff_item.setForeground(Qt.GlobalColor.green)
                self.detail_table.setItem(r, 5, diff_item)
            else:
                self.detail_table.setItem(r, 5, _cell("—", center=True))

            self.detail_table.setItem(r, 6, _cell(f"{ms:.1f}" if first else "", center=True))
            first = False

        self.detail_table.scrollToBottom()

    # ── accuracy table ────────────────────────────────────────────────────────

    def _build_accuracy_table(self):
        """Compute per-split per-class accuracy metrics and populate acc_table."""
        if not self._has_any_labels:
            self.lbl_overall.setText(
                "ไม่พบ label files (.txt)  —  แสดงเฉพาะจำนวน Predicted\n"
                "วาง label files ไว้ข้างๆ รูป หรือใน labels/ folder เพื่อดู accuracy"
            )
            self.lbl_overall.setStyleSheet(
                "color:#FFCC80; font-size:12px;"
                "background:#2a1a00; border-radius:5px; padding:5px;"
            )
            return

        # agg[split][class] = {'gt': [], 'pred': []}  — per image lists
        agg: dict[str, dict[str, dict]] = {}
        for split, _, pred, gt, _, has_labels in self._results:
            if split == 'error' or not has_labels:
                continue
            if split not in agg:
                agg[split] = {}
            all_cls = set(list(pred.keys()) + list(gt.keys()))
            for cls in all_cls:
                if cls not in agg[split]:
                    agg[split][cls] = {'gt': [], 'pred': []}
                agg[split][cls]['gt'].append(gt.get(cls, 0))
                agg[split][cls]['pred'].append(pred.get(cls, 0))

        self.acc_table.setRowCount(0)
        overall_exact = []
        overall_abs_err = []

        for split in sorted(agg.keys()):
            for cls in sorted(agg[split].keys()):
                gts   = agg[split][cls]['gt']
                preds = agg[split][cls]['pred']
                n     = len(gts)
                abs_errs = [abs(p - g) for p, g in zip(preds, gts)]
                diffs    = [p - g     for p, g in zip(preds, gts)]
                exact    = sum(1 for p, g in zip(preds, gts) if p == g)

                mae      = sum(abs_errs) / n
                count_acc = exact / n * 100
                avg_diff  = sum(diffs) / n
                gt_total  = sum(gts)
                pred_total = sum(preds)

                overall_exact.extend([p == g for p, g in zip(preds, gts)])
                overall_abs_err.extend(abs_errs)

                r = self.acc_table.rowCount()
                self.acc_table.insertRow(r)
                self.acc_table.setItem(r, 0, _cell(split))
                self.acc_table.setItem(r, 1, _cell(cls))
                self.acc_table.setItem(r, 2, _cell(str(gt_total),   center=True))
                self.acc_table.setItem(r, 3, _cell(str(pred_total), center=True))
                self.acc_table.setItem(r, 4, _cell(f"{mae:.2f}",    center=True))

                acc_item = _cell(f"{count_acc:.1f} %", center=True)
                if count_acc >= 90:
                    acc_item.setForeground(Qt.GlobalColor.green)
                elif count_acc >= 70:
                    acc_item.setForeground(Qt.GlobalColor.yellow)
                else:
                    acc_item.setForeground(Qt.GlobalColor.red)
                self.acc_table.setItem(r, 5, acc_item)

                diff_item = _cell(f"{avg_diff:+.2f}", center=True)
                if avg_diff > 0.05:
                    diff_item.setForeground(Qt.GlobalColor.yellow)
                elif avg_diff < -0.05:
                    diff_item.setForeground(Qt.GlobalColor.red)
                else:
                    diff_item.setForeground(Qt.GlobalColor.green)
                self.acc_table.setItem(r, 6, diff_item)

        # overall banner
        if overall_exact:
            oa = sum(overall_exact) / len(overall_exact) * 100
            om = sum(overall_abs_err) / len(overall_abs_err)
            self.lbl_overall.setText(
                f"Overall Count Accuracy: {oa:.1f} %   |   "
                f"Overall MAE: {om:.3f}   |   "
                f"conf = {self._conf:.2f}   |   "
                f"Images with labels: {len(overall_exact)}"
            )
            color = "#4CAF50" if oa >= 90 else ("#FF9800" if oa >= 70 else "#EF9A9A")
            self.lbl_overall.setStyleSheet(
                f"color:{color}; font-size:13px; font-weight:bold;"
                "background:#1a2a1a; border-radius:5px; padding:5px;"
            )

    # ── export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self._results:
            QMessageBox.information(self, "ไม่มีข้อมูล", "รัน batch ก่อนแล้วค่อย export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", str(_get_base_dir() / "batch_results.csv"),
            "CSV files (*.csv);;All files (*.*)"
        )
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(
                ["split", "filename", "class",
                 "gt_count", "pred_count", "diff", "latency_ms", "conf"]
            )
            for split, filename, pred, gt, ms, has_labels in self._results:
                all_cls = sorted(set(list(pred.keys()) + list(gt.keys())))
                if not all_cls:
                    writer.writerow([split, filename, "", "", 0, "", f"{ms:.1f}", self._conf])
                    continue
                first = True
                for cls in all_cls:
                    p = pred.get(cls, 0)
                    g = gt.get(cls, 0) if has_labels else ""
                    d = (p - g) if has_labels else ""
                    writer.writerow([
                        split, filename, cls, g, p, d,
                        f"{ms:.1f}" if first else "", self._conf
                    ])
                    first = False
        self._on_status(f"Export แล้ว: {Path(path).name}", "#4CAF50")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _on_status(self, msg: str, color: str):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(
            f"font-size:13px; font-weight:bold; color:{color};"
            f"background:#1e1e2e; border-radius:6px; padding:4px;"
        )


def _cell(text: str, *, center: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = BatchEvalWindow()
    win.show()
    sys.exit(app.exec())
