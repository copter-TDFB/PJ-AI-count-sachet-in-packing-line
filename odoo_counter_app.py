import sys
import ctypes
import time
import threading
import queue
import itertools
_snd_counter = itertools.count()
import xmlrpc.client
import cv2
import numpy as np
from pathlib import Path
from ultralytics import YOLO
from pynput import keyboard as pynput_kb
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QLineEdit, QFileDialog, QFrame,
    QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap

ODOO_URL      = 'https://tdfb-30042026-test.odoo.com'
ODOO_DB       = 'tdfb-30042026-test'
ODOO_USER     = 'operation.engineer@tdfb.co'
ODOO_PASSWORD = 'KBT123'

def _get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

DEFAULT_MODEL = str(_get_base_dir() / 'ai_3g_v5.pt')


# ── Connection cache ──────────────────────────────────────────
class OdooConn:
    _uid    = None
    _models = None

    @classmethod
    def ensure(cls):
        if cls._uid is None:
            common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
            uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
            if not uid:
                raise RuntimeError("Login ไม่ผ่าน")
            cls._uid    = uid
            cls._models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

    @classmethod
    def reset(cls):
        cls._uid    = None
        cls._models = None


# ── Worker: ค้นหา picking จาก barcode ───────────────────────
class BarcodeWorker(QThread):
    data_ready     = pyqtSignal(dict)
    not_found      = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, barcode: str):
        super().__init__()
        self.barcode = barcode.strip()

    def run(self):
        try:
            OdooConn.ensure()
            uid, models = OdooConn._uid, OdooConn._models

            pickings = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'stock.picking', 'search_read',
                [[['x_studio_tracking_no', '=', self.barcode],
                  ['picking_type_id.name', 'ilike', 'Pack'],
                  ['state', '=', 'assigned']]],
                {'fields': ['name', 'x_studio_tracking_no', 'partner_id', 'state'], 'limit': 1}
            )
            if not pickings:
                self.not_found.emit(self.barcode)
                return

            picking = pickings[0]
            moves = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'stock.move', 'search_read',
                [[['picking_id', '=', picking['id']],
                  ['state', 'not in', ['done', 'cancel']],
                  '|', '|', '|', '|',
                  ['product_id.name', 'ilike', 'Excellent Rich 95% 3.1g (1 sachet)'],
                  ['product_id.name', 'ilike', 'Medium Rich 95% 3.1g (1 sachet)'],
                  ['product_id.name', 'ilike', 'Classic Rich 95% 3.1g (1 sachet)'],
                  ['product_id.name', 'ilike', 'Houjicha Rich 95% 3.1g (1 sachet)'],
                  ['product_id.name', 'ilike', 'Genmaicha Powder 3 g']]],
                {'fields': ['product_id', 'product_uom_qty']}
            )
            if not moves:
                # ดึง product ทั้งหมดใน picking เพื่อดูว่าชื่อจริงคืออะไร
                all_moves = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'stock.move', 'search_read',
                    [[['picking_id', '=', picking['id']],
                      ['state', 'not in', ['done', 'cancel']]]],
                    {'fields': ['product_id', 'product_uom_qty']}
                )
                if all_moves:
                    product_names = ', '.join(
                        f"{m['product_id'][1]} ({int(m['product_uom_qty'])})"
                        for m in all_moves
                    )
                    self.not_found.emit(
                        f"{picking['name']} — ไม่พบสินค้า 3g ที่รองรับ\n"
                        f"สินค้าในใบนี้: {product_names}"
                    )
                else:
                    self.not_found.emit(f"{picking['name']} — ไม่มี moves ที่ยังไม่เสร็จในใบนี้เลย")
                return
            self.data_ready.emit({'picking': picking, 'moves': moves})

        except Exception as e:
            OdooConn.reset()
            self.error_occurred.emit(str(e))


# ── Worker: บันทึก log note กลับ Odoo ───────────────────────
class OdooSaveWorker(QThread):
    save_done  = pyqtSignal()
    save_error = pyqtSignal(str)

    def __init__(self, picking_id: int, product_counts: list):
        super().__init__()
        self.picking_id    = picking_id
        self.product_counts = product_counts

    def run(self):
        try:
            OdooConn.ensure()
            uid    = OdooConn._uid
            models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

            body = ', '.join(
                f"AI นับ {pc['product_name']}: นับได้ {pc['counted']} / {int(pc['demand'])} pcs"
                for pc in self.product_counts
            )
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'stock.picking', 'message_post',
                [[self.picking_id]],
                {'body': body, 'message_type': 'comment', 'subtype_xmlid': 'mail.mt_note'}
            )
            self.save_done.emit()

        except Exception as e:
            self.save_error.emit(str(e))


# ── Global keyboard listener (รับ barcode แม้ app ถูก minimize) ──
class GlobalBarcodeListener(QThread):
    barcode_ready  = pyqtSignal(str)
    buffer_updated = pyqtSignal(str)

    _TIMEOUT = 0.15  # reset buffer ถ้า gap ระหว่าง key > 150ms

    def __init__(self):
        super().__init__()
        self._buffer    = []
        self._last_time = 0.0
        self._active    = True
        self._suppress  = False  # True เมื่อ app มี focus — ให้ Qt จัดการแทน
        self._listener  = None

    def set_active(self, val: bool):
        self._active = val
        if not val:
            self._buffer = []
            self.buffer_updated.emit('')

    def set_suppress(self, val: bool):
        self._suppress = val
        if val:
            self._buffer = []

    def _on_press(self, key):
        if not self._active or self._suppress:
            return
        now = time.monotonic()
        if now - self._last_time > self._TIMEOUT:
            self._buffer = []
        self._last_time = now
        try:
            char = key.char
            if char:
                self._buffer.append(char)
                self.buffer_updated.emit(''.join(self._buffer))
        except AttributeError:
            if key == pynput_kb.Key.enter:
                barcode = ''.join(self._buffer)
                self._buffer = []
                self.buffer_updated.emit('')
                if len(barcode) >= 4:
                    self.barcode_ready.emit(barcode)
            elif key == pynput_kb.Key.backspace and self._buffer:
                self._buffer.pop()
                self.buffer_updated.emit(''.join(self._buffer))

    def run(self):
        with pynput_kb.Listener(on_press=self._on_press) as listener:
            self._listener = listener
            listener.join()

    def stop_listener(self):
        if self._listener:
            self._listener.stop()


_OBB_COLORS = {
    'excellent': (  0,  80,   0),
    'medium':    (  0, 220,   0),
    'classic':   (180, 255, 180),
    'genmaicha': ( 50, 205, 154),
    'houjicha':  ( 43,  90, 139),
}
_OBB_LABELS = {
    'excellent': 'Excellent Rich',
    'medium':    'Medium Rich',
    'classic':   'Classic Rich',
    'genmaicha': 'Genmaicha Powder',
    'houjicha':  'Houjicha Rich',
}
_KEYWORD_ODOO_NAME = {
    'excellent': 'Excellent Rich 95% 3.1g',
    'medium':    'Medium Rich 95% 3.1g',
    'classic':   'Classic Rich 95% 3.1g',
    'houjicha':  'Houjicha Rich 95% 3.1g',
    'genmaicha': 'Genmaicha Powder 3 g',
}

def _draw_obb(frame: np.ndarray, res, names: dict) -> np.ndarray:
    out    = frame.copy()
    counts: dict[str, int] = {}

    if res.obb is not None and len(res.obb) > 0:
        pts_all = res.obb.xyxyxyxy.cpu().numpy().astype(int)
        for i, cls_idx in enumerate(res.obb.cls.tolist()):
            name  = names[int(cls_idx)].lower()
            color = next((c for kw, c in _OBB_COLORS.items() if kw in name), (200, 200, 200))
            cv2.polylines(out, [pts_all[i]], isClosed=True, color=color, thickness=3)
            for kw in _OBB_COLORS:
                if kw in name:
                    counts[kw] = counts.get(kw, 0) + 1
                    break

    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 1.5, 2
    pad, line_h = 12, 54
    (ref_w, _), _ = cv2.getTextSize('Genmaicha: 00', font, scale, thick)
    x0 = out.shape[1] - ref_w - pad * 2

    for idx, (kw, base_color) in enumerate(_OBB_COLORS.items()):
        cnt   = counts.get(kw, 0)
        color = base_color if cnt > 0 else tuple(int(c * 0.35) for c in base_color)
        label = f"{_OBB_LABELS[kw]}: {cnt}"
        y     = pad + (idx + 1) * line_h
        (tw, th), _ = cv2.getTextSize(label, font, scale, thick)
        cv2.rectangle(out, (x0 - 8, y - th - 8), (x0 + tw + 8, y + 8), (20, 20, 20), -1)
        cv2.putText(out, label, (x0, y), font, scale, color, thick, cv2.LINE_AA)

    return out


# ── Worker: กล้อง + YOLO inference ─────────────────────────
class CameraWorker(QThread):
    frame_ready        = pyqtSignal(QImage, object)
    status_message     = pyqtSignal(str)
    model_ready        = pyqtSignal(str)
    image_infer_done   = pyqtSignal(QImage, object)
    image_infer_error  = pyqtSignal(str)

    def __init__(self, model_path: str, camera_id: int = 0, conf: float = 0.5):
        super().__init__()
        self.model_path = model_path
        self.camera_id  = camera_id
        self.conf       = conf
        self._running   = True
        self._img_req   = queue.Queue(maxsize=1)

    def infer_image(self, image_path: str):
        try:
            self._img_req.put_nowait(image_path)
        except queue.Full:
            pass

    def stop(self):
        self._running = False

    def run(self):
        pt_path = Path(self.model_path)
        ov_path = pt_path.parent / (pt_path.stem + '_openvino_model')

        if pt_path.suffix == '.pt' and not ov_path.exists():
            self.status_message.emit("กำลัง export OpenVINO (รอสักครู่)...")
            try:
                tmp = YOLO(str(pt_path), task='obb')
                tmp.export(format='openvino', half=False)
                del tmp
            except Exception as e:
                print(f"[OpenVINO] Export ล้มเหลว: {e}", flush=True)

        if ov_path.exists():
            try:
                model = YOLO(str(ov_path), task='obb')
                model_path_used = str(ov_path)
            except Exception:
                self.status_message.emit("OpenVINO ไม่รองรับใน .exe — ใช้ .pt แทน")
                model = YOLO(str(pt_path), task='obb')
                model_path_used = str(pt_path)
        else:
            model = YOLO(str(pt_path), task='obb')
            model_path_used = str(pt_path)

        loaded_name = Path(model_path_used).name
        self.status_message.emit(f"โหลด {loaded_name} สำเร็จ — พร้อมนับ")
        self.model_ready.emit(loaded_name)

        cap = cv2.VideoCapture(self.camera_id)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        state = {'annotated': None, 'class_counts': {}, 'new': False}
        lock  = threading.Lock()
        q     = queue.Queue(maxsize=1)

        def _infer():
            while self._running:
                # one-shot image request (ใช้ model ที่โหลดไว้แล้ว ไม่โหลดซ้ำ)
                try:
                    img_path  = self._img_req.get_nowait()
                    img_bytes = Path(img_path).read_bytes()
                    arr       = np.frombuffer(img_bytes, dtype=np.uint8)
                    img_frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img_frame is None:
                        self.image_infer_error.emit(f"เปิดไฟล์ไม่ได้: {Path(img_path).name}")
                    else:
                        res = model(img_frame, conf=self.conf, verbose=False)[0]
                        cc  = {}
                        if res.obb is not None and len(res.obb) > 0:
                            for cls_idx in res.obb.cls.tolist():
                                name     = model.names[int(cls_idx)]
                                cc[name] = cc.get(name, 0) + 1
                        annotated = _draw_obb(img_frame, res, model.names)
                        rgb       = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                        h, w, ch  = rgb.shape
                        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                        self.image_infer_done.emit(qimg, cc)
                except queue.Empty:
                    pass
                except Exception as e:
                    self.image_infer_error.emit(str(e))

                # camera frame inference
                try:
                    frame = q.get(timeout=0.05)
                    h, w = frame.shape[:2]
                    # 1) crop center → 16:9
                    target = 16 / 9
                    current = w / h
                    if current > target:
                        new_w = int(round(h * target))
                        x     = (w - new_w) // 2
                        frame = frame[:, x:x + new_w]
                    elif current < target:
                        new_h = int(round(w / target))
                        y     = (h - new_h) // 2
                        frame = frame[y:y + new_h, :]
                    # 2) downscale to 1080p only if larger
                    if frame.shape[0] > 1080:
                        frame = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
                    t0    = time.perf_counter()
                    res   = model(frame, conf=self.conf, verbose=False)[0]
                    ms    = (time.perf_counter() - t0) * 1000
                    cc    = {}
                    if res.obb is not None and len(res.obb) > 0:
                        for cls_idx in res.obb.cls.tolist():
                            name = model.names[int(cls_idx)]
                            cc[name] = cc.get(name, 0) + 1
                    fps = 1000 / ms if ms > 0 else 0
                    print(f"[Detect] {ms:.1f} ms  |  {fps:.1f} FPS  |  {cc}", flush=True)
                    annotated = _draw_obb(frame, res, model.names)
                    cv2.putText(
                        annotated,
                        f"FPS: {fps:.1f}  |  Latency: {ms:.1f} ms",
                        (10, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                        (0, 255, 80), 2, cv2.LINE_AA,
                    )
                    with lock:
                        state['annotated']    = annotated
                        state['class_counts'] = cc
                        state['new']          = True
                except queue.Empty:
                    pass
                except Exception as e:
                    self.status_message.emit(f"Inference error: {e}")

        threading.Thread(target=_infer, daemon=True).start()

        interval = 1.0 / 15
        while self._running:
            t0 = time.perf_counter()
            ret, frame = cap.read()
            if not ret:
                continue
            frame = cv2.flip(frame, 1)

            try:
                q.put_nowait(frame)
            except queue.Full:
                pass

            with lock:
                is_new       = state['new']
                disp         = state['annotated']
                class_counts = dict(state['class_counts'])
                if is_new:
                    state['new'] = False

            if is_new or disp is None:
                disp = disp if disp is not None else frame
                rgb  = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                self.frame_ready.emit(qimg, class_counts)

            elapsed  = time.perf_counter() - t0
            sleep_ms = max(0, int((interval - elapsed) * 1000))
            if sleep_ms > 0:
                self.msleep(sleep_ms)

        cap.release()


# ── หน้าต่างนับ (เด้งขึ้นเมื่อเจอ Excellent/Houjicha 3g) ────
class CounterPanel(QWidget):
    closed                 = pyqtSignal()
    image_infer_requested  = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI นับซอง")
        self.resize(1380, 800)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        self._current_entry      = None
        self._product_rows       = []
        self._last_class_counts  = {}
        self._log_posted         = False
        self._stable_since       = None
        self._last_stable_counts: dict = {}
        self._last_sound_status: str | None = None
        self._image_mode         = False
        self._save_workers: set  = set()

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(1500)
        self._toast_timer.timeout.connect(self._hide_toast)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(1500)
        self._hide_timer.timeout.connect(self.hide)

        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── LEFT: Camera ─────────────────────────────────
        self.camera_label = QLabel("กำลังโหลดกล้อง...")
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setMinimumSize(900, 720)
        self.camera_label.setStyleSheet(
            "background:#1a1a1a; color:#666; font-size:15px; border-radius:8px;"
        )
        root.addWidget(self.camera_label, 1)

        self.lbl_toast = QLabel(self.camera_label)
        self.lbl_toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_toast.setWordWrap(True)
        self.lbl_toast.hide()

        # ── RIGHT: Info panel ────────────────────────────
        right_panel = QWidget()
        right_panel.setFixedWidth(380)
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        self.lbl_picking_info = QLabel("—")
        self.lbl_picking_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_picking_info.setWordWrap(True)
        self.lbl_picking_info.setStyleSheet(
            "font-size:14px; font-weight:bold; color:#90CAF9;"
            "background:#1e1e2e; border-radius:8px; padding:10px;"
        )
        self.lbl_picking_info.setMinimumHeight(60)
        right.addWidget(self.lbl_picking_info)

        cards_box = QGroupBox("จำนวนที่นับ")
        cards_box.setStyleSheet(
            "QGroupBox { font-size:13px; font-weight:bold; color:#aaa;"
            "border:1px solid #333; border-radius:8px; margin-top:10px; padding-top:6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 6px; }"
        )
        cb_layout = QVBoxLayout(cards_box)
        cb_layout.setContentsMargins(8, 12, 8, 8)
        cb_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_inner = QWidget()
        self._cards_layout = QVBoxLayout(scroll_inner)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch(1)
        scroll.setWidget(scroll_inner)
        cb_layout.addWidget(scroll)
        right.addWidget(cards_box, 1)

        self.lbl_wrong = QLabel()
        self.lbl_wrong.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_wrong.setWordWrap(True)
        self.lbl_wrong.setStyleSheet(
            "background:#B71C1C; color:white; font-size:13px; font-weight:bold;"
            "border-radius:8px; padding:10px;"
        )
        self.lbl_wrong.setMinimumHeight(50)
        self.lbl_wrong.hide()
        right.addWidget(self.lbl_wrong)

        self.btn_upload = QPushButton("📁 อัพโหลดรูปภาพ")
        self.btn_upload.setFixedHeight(40)
        self.btn_upload.setStyleSheet(
            "font-size:13px; background:#1565C0; color:white; border-radius:6px;"
        )
        self.btn_upload.clicked.connect(self._open_image)
        right.addWidget(self.btn_upload)

        self.btn_back_cam = QPushButton("📷 กลับกล้อง")
        self.btn_back_cam.setFixedHeight(40)
        self.btn_back_cam.setStyleSheet(
            "font-size:13px; background:#2E7D32; color:white; border-radius:6px;"
        )
        self.btn_back_cam.clicked.connect(self._back_to_camera)
        self.btn_back_cam.hide()
        right.addWidget(self.btn_back_cam)

        btn_close = QPushButton("ปิด — สแกนใบใหม่")
        btn_close.setFixedHeight(45)
        btn_close.setStyleSheet(
            "font-size:14px; background:#37474F; color:white; border-radius:6px;"
        )
        btn_close.clicked.connect(self.hide)
        right.addWidget(btn_close)

        root.addWidget(right_panel, 0)

    def popup(self, entry: dict):
        self._hide_timer.stop()
        self._image_mode = False
        self.btn_upload.setEnabled(True)
        self.btn_upload.setText("📁 อัพโหลดรูปภาพ")
        self.btn_back_cam.hide()
        self._current_entry = entry
        p        = entry['picking']
        contact  = p['partner_id'][1] if p['partner_id'] else '-'
        state_th = {'assigned': 'พร้อม', 'done': 'เสร็จแล้ว', 'waiting': 'รอ',
                    'confirmed': 'ยืนยัน', 'cancel': 'ยกเลิก'}.get(p['state'], p['state'])
        self.lbl_picking_info.setText(f"  {p['name']}   |   {contact}   |   {state_th}")
        self._build_count_table(entry['moves'])

        self.show()
        self.activateWindow()
        self.raise_()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except Exception:
            pass

    def update_frame(self, qimg: QImage, class_counts: dict):
        if self._image_mode:
            return
        self._show_frame(qimg)
        self._apply_counts(class_counts, stable_check=True)

    def _show_frame(self, qimg: QImage):
        pix = QPixmap.fromImage(qimg).scaled(
            self.camera_label.width(),
            self.camera_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation
        )
        self.camera_label.setPixmap(pix)

    def _apply_counts(self, class_counts: dict, stable_check: bool = False):
        self._last_class_counts = class_counts
        now       = time.monotonic()
        all_exact    = bool(self._product_rows)
        any_over     = False
        any_counted  = False
        current_counts: dict = {}

        for pr in self._product_rows:
            cnt    = self._get_count(class_counts, pr['keyword'])
            demand = int(pr['demand'])
            current_counts[id(pr)] = cnt
            if cnt > 0:
                any_counted = True

            if cnt == demand:
                color, stat = '#4CAF50', '✓ ครบแล้ว'
            elif cnt > demand:
                color, stat = '#F44336', f'เกิน {cnt - demand}'
                all_exact = False
                any_over  = True
            else:
                color, stat = '#FF9800', f'ขาด {demand - cnt}'
                all_exact = False

            pr['lbl_count'].setText(str(cnt))
            pr['lbl_count'].setStyleSheet(
                f"font-size:34px; color:{color}; font-weight:bold;"
            )
            pr['lbl_status'].setText(stat)
            pr['lbl_status'].setStyleSheet(
                f"background:{color}; color:white; font-size:13px; font-weight:bold;"
                f"border-radius:6px; padding:6px 12px;"
            )

        # Reset stability timer when counts change; clear last sound to allow re-notify
        if current_counts != self._last_stable_counts:
            self._stable_since       = now
            self._last_stable_counts = current_counts.copy()
            self._last_sound_status  = None

        if stable_check:
            if any_counted and self._stable_since is not None and now - self._stable_since >= 0.5:
                status_key = 'exact' if all_exact else ('over' if any_over else 'under')
                if status_key != self._last_sound_status:
                    self._last_sound_status = status_key
                    self._play_sound(status_key)
                if all_exact and not self._log_posted:
                    self._save_to_odoo()
        else:
            # Image mode — immediate result
            if any_counted:
                status_key = 'exact' if all_exact else ('over' if any_over else 'under')
                self._play_sound(status_key)
            if all_exact and not self._log_posted:
                self._save_to_odoo()

        # ตรวจสอบสินค้าที่ detect ได้แต่ไม่อยู่ใน order
        if self._product_rows:
            order_kws = {pr['keyword'] for pr in self._product_rows}
            wrong = [
                name for name, cnt in class_counts.items()
                if cnt > 0 and not any(kw in name.lower() for kw in order_kws)
            ]
            if wrong:
                odoo_names = []
                for n in wrong:
                    kw = next((k for k in _KEYWORD_ODOO_NAME if k in n.lower()), None)
                    odoo_names.append(_KEYWORD_ODOO_NAME[kw] if kw else n)
                self.lbl_wrong.setText(f"⚠ พบสินค้าที่ไม่ใช่ใน Order: {', '.join(odoo_names)}")
                self.lbl_wrong.show()
            else:
                self.lbl_wrong.hide()

    @staticmethod
    def _play_sound(status: str):
        fname = 'ถูก.mp3' if status == 'exact' else 'ผิด.mp3'
        path  = str(_get_base_dir() / fname)
        alias = f'snd{next(_snd_counter)}'
        def _play():
            try:
                mci = ctypes.windll.winmm.mciSendStringW
                mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
                mci(f'play {alias} wait', None, 0, None)
                mci(f'close {alias}', None, 0, None)
            except Exception:
                pass
        threading.Thread(target=_play, daemon=True).start()

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "เลือกรูปภาพ", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.webp)"
        )
        if not path:
            return
        self.btn_upload.setEnabled(False)
        self.btn_upload.setText("⏳ กำลังประมวลผล...")
        self.image_infer_requested.emit(path)

    def _on_image_result(self, qimg: QImage, class_counts: dict):
        self._image_mode = True
        self._show_frame(qimg)
        self._apply_counts(class_counts, stable_check=False)
        self.btn_upload.setEnabled(True)
        self.btn_upload.setText("📁 เปลี่ยนรูปภาพ")
        self.btn_back_cam.show()

    def _on_infer_error(self, msg: str):
        self.btn_upload.setEnabled(True)
        self.btn_upload.setText("📁 อัพโหลดรูปภาพ")
        self._show_toast(f"✗ {msg}", success=False)

    def _back_to_camera(self):
        self._image_mode = False
        self.camera_label.clear()
        self.camera_label.setText("รอ frame จากกล้อง...")
        self.btn_upload.setText("📁 อัพโหลดรูปภาพ")
        self.btn_back_cam.hide()

    @staticmethod
    def _get_count(class_counts: dict, keyword: str) -> int:
        for cls_name, cnt in class_counts.items():
            if keyword in cls_name.lower():
                return cnt
        return 0

    def _build_count_table(self, moves):
        self._product_rows       = []
        self._log_posted         = False
        self._stable_since       = None
        self._last_stable_counts = {}
        self._last_sound_status  = None
        self.lbl_wrong.hide()

        # Clear existing cards (keep stretch at the end)
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for m in moves:
            pname   = self._strip_ref(m['product_id'][1])
            keyword = self._extract_keyword(pname)
            demand  = int(m['product_uom_qty'])
            card, lbl_count, lbl_status = self._create_product_card(pname, demand)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._product_rows.append({
                'product_name': pname,
                'demand':       m['product_uom_qty'],
                'keyword':      keyword,
                'card':         card,
                'lbl_count':    lbl_count,
                'lbl_status':   lbl_status,
            })

    @staticmethod
    def _create_product_card(name: str, demand: int):
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background:#252535; border-radius:8px; }"
        )
        card.setMinimumHeight(96)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 8, 12, 10)
        cl.setSpacing(2)

        lbl_name = QLabel(name)
        lbl_name.setStyleSheet("font-size:12px; color:#bbb; font-weight:bold;")
        lbl_name.setWordWrap(True)
        cl.addWidget(lbl_name)

        row = QHBoxLayout()
        row.setSpacing(6)

        lbl_count = QLabel("0")
        lbl_count.setStyleSheet("font-size:34px; color:#FF9800; font-weight:bold;")
        lbl_count.setAlignment(Qt.AlignmentFlag.AlignBottom)

        lbl_sep = QLabel(f"/ {demand}")
        lbl_sep.setStyleSheet("font-size:18px; color:#777;")
        lbl_sep.setAlignment(Qt.AlignmentFlag.AlignBottom)

        row.addWidget(lbl_count)
        row.addWidget(lbl_sep)
        row.addStretch(1)

        lbl_status = QLabel(f"ขาด {demand}")
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_status.setStyleSheet(
            "background:#FF9800; color:white; font-size:13px; font-weight:bold;"
            "border-radius:6px; padding:6px 12px;"
        )
        lbl_status.setMinimumWidth(95)
        row.addWidget(lbl_status)

        cl.addLayout(row)
        return card, lbl_count, lbl_status

    @staticmethod
    def _strip_ref(name: str) -> str:
        if name.startswith('['):
            idx = name.find(']')
            if idx != -1:
                name = name[idx + 1:].strip()
        if ' (' in name:
            name = name.split(' (')[0].strip()
        return name

    @staticmethod
    def _extract_keyword(product_name: str) -> str:
        pn = product_name.lower()
        for kw in ('excellent', 'medium', 'classic', 'houjicha', 'genmaicha'):
            if kw in pn:
                return kw
        return pn.split()[0]

    def _save_to_odoo(self):
        if not self._current_entry:
            return
        self._log_posted = True
        product_counts = [
            {
                'product_name': pr['product_name'],
                'counted':      self._get_count(self._last_class_counts, pr['keyword']),
                'demand':       pr['demand'],
            }
            for pr in self._product_rows
        ]
        w = OdooSaveWorker(self._current_entry['picking']['id'], product_counts)
        w.save_done.connect(self._on_save_done)
        w.save_error.connect(self._on_save_error)
        w.finished.connect(lambda: self._save_workers.discard(w))
        self._save_workers.add(w)
        w.start()

    def _on_save_done(self):
        self._show_toast("✓ ครบตามจำนวนใน order\nบันทึก log ในใบ pack สำเร็จ", success=True)
        self._hide_timer.start()

    def _on_save_error(self, msg: str):
        self._show_toast(f"✗ บันทึกไม่สำเร็จ\n{msg}", success=False)

    def _show_toast(self, msg: str, success: bool = True):
        color = "#4CAF50" if success else "#F44336"
        self.lbl_toast.setStyleSheet(
            f"background: rgba(0,0,0,210); color: {color}; font-size: 26px; font-weight: bold;"
            f"border-radius: 14px; padding: 18px 28px;"
        )
        self.lbl_toast.setText(msg)
        p = self.camera_label
        w, h = min(620, p.width() - 40), 150
        self.lbl_toast.setGeometry((p.width() - w) // 2, (p.height() - h) // 2, w, h)
        self.lbl_toast.show()
        self.lbl_toast.raise_()
        self._toast_timer.start()

    def _hide_toast(self):
        self.lbl_toast.hide()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.closed.emit()


# ── หน้าต่าง Barcode (เล็ก ใช้ตลอด) ────────────────────────
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Odoo Pack Counter")
        self.setFixedWidth(600)

        self._counter_panel = CounterPanel()
        self._counter_panel.closed.connect(self._on_counter_closed)
        self._camera_worker = None
        self._workers: set  = set()

        self._barcode_listener = GlobalBarcodeListener()
        self._barcode_listener.barcode_ready.connect(self._on_barcode_scanned)
        self._barcode_listener.buffer_updated.connect(self._on_buffer_updated)
        self._barcode_listener.start()

        self._build_ui()
        self._start_camera()
        QApplication.instance().focusChanged.connect(self._on_app_focus_changed)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)

        bc_box = QGroupBox("Barcode Scanner")
        bc_lay = QHBoxLayout(bc_box)
        bc_lay.setContentsMargins(10, 6, 10, 6)

        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("พิมพ์หรือสแกน Barcode แล้วกด Enter  (ใช้ได้แม้ย่อ app ไว้)")
        self.barcode_input.setFixedHeight(40)
        self.barcode_input.setStyleSheet("font-size:15px; padding:4px 10px;")
        self.barcode_input.returnPressed.connect(self._on_returnpressed)

        self.lbl_bc_icon = QLabel("⬜")
        self.lbl_bc_icon.setFixedWidth(30)
        self.lbl_bc_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_bc_icon.setStyleSheet("font-size:20px;")

        bc_lay.addWidget(self.barcode_input)
        bc_lay.addWidget(self.lbl_bc_icon)
        root.addWidget(bc_box)

        self.lbl_status = QLabel("กำลังโหลด model และกล้อง...")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        root.addWidget(self.lbl_status)

    def _start_camera(self):
        self._camera_worker = CameraWorker(DEFAULT_MODEL)
        self._camera_worker.frame_ready.connect(self._on_frame)
        self._camera_worker.status_message.connect(self.lbl_status.setText)
        self._camera_worker.model_ready.connect(self._on_model_ready)
        self._camera_worker.image_infer_done.connect(self._counter_panel._on_image_result)
        self._camera_worker.image_infer_error.connect(self._counter_panel._on_infer_error)
        self._counter_panel.image_infer_requested.connect(self._camera_worker.infer_image)
        self._camera_worker.start()

    def _on_model_ready(self, name: str):
        color = "#FF9800" if "openvino" in name.lower() else "#4CAF50"
        self.lbl_status.setText(f"Model: {name}  ●  กล้องพร้อม — รอสแกน Barcode")
        self.lbl_status.setStyleSheet(f"color:{color}; font-size:12px; font-weight:bold;")

    def _on_frame(self, qimg: QImage, class_counts: dict):
        if self._counter_panel.isVisible():
            self._counter_panel.update_frame(qimg, class_counts)

    def _on_app_focus_changed(self, _, new_widget):
        # new_widget is None เมื่อ app ไม่มี focus → ให้ global listener ทำงาน
        self._barcode_listener.set_suppress(new_widget is not None)

    def _on_buffer_updated(self, text: str):
        # อัปเดต display เฉพาะตอน app ไม่มี focus (global listener ทำงาน)
        if not self._barcode_listener._suppress:
            self.barcode_input.setText(text)

    def _on_returnpressed(self):
        barcode = self.barcode_input.text().strip()
        if not barcode:
            return
        self.barcode_input.clear()
        self._on_barcode_scanned(barcode)

    def _on_barcode_scanned(self, barcode: str):
        self.lbl_bc_icon.setText("⏳")
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        self.lbl_status.setText(f"กำลังค้นหา {barcode} ...")
        w = BarcodeWorker(barcode)
        w.data_ready.connect(self._on_barcode_data)
        w.not_found.connect(self._on_not_found)
        w.error_occurred.connect(self._on_error)
        w.finished.connect(lambda: self._workers.discard(w))
        self._workers.add(w)
        w.start()

    def _on_counter_closed(self):
        self._barcode_listener.set_active(True)
        self.lbl_bc_icon.setText("⬜")
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        self.lbl_status.setText("ปิดหน้าต่างนับแล้ว — พร้อมสแกนใบใหม่")

    def _on_barcode_data(self, entry: dict):
        self.lbl_bc_icon.setText("✅")
        self.lbl_status.setStyleSheet("color:#4CAF50; font-size:12px; font-weight:bold;")
        self.lbl_status.setText(f"พบ {entry['picking']['name']} — เปิดหน้าต่างนับ")
        self._barcode_listener.set_active(False)
        self._counter_panel.popup(entry)

    def _on_not_found(self, msg: str):
        self.lbl_bc_icon.setText("❌")
        self.lbl_status.setStyleSheet("color:#EF9A9A; font-size:12px;")
        self.lbl_status.setText(msg)

    def _on_error(self, msg: str):
        self.lbl_bc_icon.setText("❌")
        self.lbl_status.setStyleSheet("color:#EF9A9A; font-size:12px;")
        self.lbl_status.setText(f"Error: {msg}")

    def closeEvent(self, event):
        self._barcode_listener.stop_listener()
        self._barcode_listener.wait()
        if self._camera_worker:
            self._camera_worker.stop()
            self._camera_worker.wait()
        self._counter_panel.close()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
