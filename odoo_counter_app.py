import sys
import os
import ctypes
import json
import time
import asyncio
import threading
import queue
import subprocess
import itertools
import tempfile
from collections import deque
_snd_counter = itertools.count()
import xmlrpc.client
import requests
import cv2
import numpy as np
import websockets
from pathlib import Path
from ultralytics import YOLO
from pynput import keyboard as pynput_kb
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QLineEdit, QFileDialog, QFrame,
    QScrollArea, QDialog, QSlider, QComboBox, QCheckBox
)
from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal, QTimer, QRect
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont, QFontMetrics
from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo

ODOO_URL      = 'https://tdfb.odoo.com'
ODOO_DB       = 'tdfb'
ODOO_USER     = 'operation.engineer@tdfb.co'
ODOO_PASSWORD = 'KBT123'
SHOP_IDENTITY_FIELD = 'x_studio_sender_name'  # sale.order many2one — validated against real data, see KAN-53 spike

def _get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

DEFAULT_MODEL = str(_get_base_dir() / 'ai_3g_v12.pt')


# ── Settings config (per-machine: crop rect + conf threshold) ─
# Legacy (pre-KAN-49) location, inside the app's own base dir. The launcher's auto-update
# wipes and recreates that whole directory (see launcher.py _install()), which used to wipe
# this file too. Kept as-is; it is now only the one-time migration source below.
def _crop_config_path() -> Path:
    return _get_base_dir() / 'crop_config.json'

# Current location: outside the app folder entirely, so app-folder replacement on
# auto-update never touches it.
def _config_path() -> Path:
    local_appdata = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(local_appdata) / 'odoo-counter' / 'config.json'

DEFAULT_CONF = 0.7

def _load_config_dict() -> dict:
    new_path = _config_path()
    if not new_path.exists():
        # One-time migration from the legacy location. Once config.json exists at the new
        # location it is the sole source of truth; legacy edits after this point are never
        # re-migrated.
        legacy_path = _crop_config_path()
        if not legacy_path.exists():
            return {}
        try:
            legacy_dict = json.loads(legacy_path.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"[Config] ไม่สามารถอ่าน legacy config {legacy_path}: {e}", flush=True)
            return {}
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(json.dumps(legacy_dict, indent=2), encoding='utf-8')
        except Exception as e:
            # best-effort; still return the migrated values for this call
            print(f"[Config] migrate เขียน {new_path} ไม่สำเร็จ: {e}", flush=True)
        return legacy_dict
    try:
        return json.loads(new_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"[Config] อ่าน {new_path} ไม่สำเร็จ (จะใช้ค่า default): {e}", flush=True)
        return {}

def _load_crop() -> tuple:
    d = _load_config_dict()
    try:
        x = max(0.0, min(1.0, float(d.get('x', 0.0))))
        y = max(0.0, min(1.0, float(d.get('y', 0.0))))
        w = max(0.05, min(1.0 - x, float(d.get('w', 1.0))))
        h = max(0.05, min(1.0 - y, float(d.get('h', 1.0))))
        return (x, y, w, h)
    except Exception:
        return (0.0, 0.0, 1.0, 1.0)

def _load_conf() -> float:
    d = _load_config_dict()
    try:
        return max(0.05, min(0.95, float(d.get('conf', DEFAULT_CONF))))
    except Exception:
        return DEFAULT_CONF

def _save_settings(rect: tuple, conf: float):
    x, y, w, h = rect
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    d = _load_config_dict()
    d.update({'x': x, 'y': y, 'w': w, 'h': h, 'conf': conf})
    config_path.write_text(json.dumps(d, indent=2), encoding='utf-8')


def _save_invoice_printer(name: str):
    """Sibling of _save_settings() for the invoice printer selection (KAN-50) — same
    merge-based save (loads the full dict, updates only invoice_printer_name, writes back),
    kept separate so _save_settings' own signature/behavior stays untouched."""
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    d = _load_config_dict()
    d.update({'invoice_printer_name': name})
    config_path.write_text(json.dumps(d, indent=2), encoding='utf-8')


def _default_sumatra_path() -> str:
    """build.ps1 bundles a portable SumatraPDF.exe under app/SumatraPDF/ so a fresh machine
    needs zero setup; fall back to the common per-machine install path if it's missing
    (e.g. running from source without the bundled copy)."""
    bundled = _get_base_dir() / 'SumatraPDF' / 'SumatraPDF.exe'
    if bundled.exists():
        return str(bundled)
    return r'C:\Program Files\SumatraPDF\SumatraPDF.exe'


def _save_invoice_auto_print(enabled: bool):
    """Sibling of _save_invoice_printer() for the invoice auto-print toggle (KAN-125) —
    loads full dict, updates invoice_auto_print_enabled, writes back."""
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    d = _load_config_dict()
    d.update({'invoice_auto_print_enabled': enabled})
    config_path.write_text(json.dumps(d, indent=2), encoding='utf-8')


def _save_invoice_auto_create(enabled: bool):
    """Sibling of _save_invoice_auto_print() for the invoice auto-create-if-missing kill
    switch — same merge-based save, kept as its own key so it can be toggled independently
    of auto-print."""
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    d = _load_config_dict()
    d.update({'invoice_auto_create_enabled': enabled})
    config_path.write_text(json.dumps(d, indent=2), encoding='utf-8')


def _load_invoice_config() -> dict:
    """Invoice auto-print settings (KAN-47), read from the same crop_config.json.
    Printer-picker UI lives in CropSettingsDialog (KAN-50) — printer_name is set there and
    persisted via _save_invoice_printer(), no more hand-editing the JSON file."""
    d = _load_config_dict()
    printer_name           = d.get('invoice_printer_name')
    auto_print_enabled     = d.get('invoice_auto_print_enabled')
    auto_create_enabled    = d.get('invoice_auto_create_enabled')
    report_id              = d.get('invoice_report_id')
    cr_report_id           = d.get('invoice_cr_report_id')
    sumatra_path           = d.get('invoice_sumatra_path')
    need_bill_field        = d.get('invoice_need_bill_field')
    need_bill_value        = d.get('invoice_need_bill_value')
    need_bill_credit_value = d.get('invoice_need_bill_credit_value')
    return {
        'printer_name':        printer_name if isinstance(printer_name, str) else '',
        'auto_print_enabled':  auto_print_enabled if isinstance(auto_print_enabled, bool) else True,
        'auto_create_enabled': auto_create_enabled if isinstance(auto_create_enabled, bool) else True,
        'report_id':           report_id if isinstance(report_id, int) else 1204,
        'cr_report_id':        cr_report_id if isinstance(cr_report_id, int) else 1200,
        'sumatra_path':        sumatra_path if isinstance(sumatra_path, str) and sumatra_path
                                else _default_sumatra_path(),
        'need_bill_field':     need_bill_field if isinstance(need_bill_field, str) and need_bill_field
                                else 'x_studio_need_bill',
        'need_bill_value':     need_bill_value if isinstance(need_bill_value, str) and need_bill_value
                                else 'ปริ้นใบเสร็จ',
        'need_bill_credit_value': need_bill_credit_value
                                if isinstance(need_bill_credit_value, str) and need_bill_credit_value
                                else 'ปริ้นใบกำกับ (เครดิต)',
    }


def _resolve_documents_to_print(need_bill: str, cfg: dict) -> list[tuple[int, str]]:
    """Maps a matched need_bill value to the ordered list of (report_id, label) to
    download and print. Empty list means need_bill matched neither known value —
    caller logs and skips, unchanged from before this function existed."""
    need_bill = (need_bill or '').strip()
    if need_bill == cfg['need_bill_value']:
        return [(cfg['report_id'], str(cfg['report_id']))]
    if need_bill == cfg['need_bill_credit_value']:
        return [
            (cfg['report_id'], str(cfg['report_id'])),
            (cfg['cr_report_id'], f"Cr.({cfg['cr_report_id']})"),
        ]
    return []


# ── Connection cache ──────────────────────────────────────────
class _LockingProxy:
    """Wraps a shared xmlrpc.client.ServerProxy so every RPC call serializes on one lock.
    ServerProxy keeps a single keep-alive HTTP connection; BarcodeWorker and InvoicePrintWorker
    run as separate QThreads and both call execute_kw on the same cached instance — without
    this, concurrent calls corrupt the connection's state (http.client.CannotSendRequest:
    Request-sent), which is what KAN-47's invoice download was silently hitting.
    """
    def __init__(self, proxy, lock: threading.Lock):
        self._proxy = proxy
        self._lock = lock

    def __getattr__(self, name):
        attr = getattr(self._proxy, name)
        def locked_call(*args, **kwargs):
            with self._lock:
                return attr(*args, **kwargs)
        return locked_call


class OdooConn:
    _uid    = None
    _models = None
    _lock   = threading.Lock()

    @classmethod
    def ensure(cls):
        if cls._uid is None:
            with cls._lock:
                if cls._uid is None:
                    common = xmlrpc.client.ServerProxy(
                        f"{ODOO_URL}/xmlrpc/2/common",
                        transport=_PingTransport(timeout=10.0),
                    )
                    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
                    if not uid:
                        raise RuntimeError("Login ไม่ผ่าน")
                    raw_models = xmlrpc.client.ServerProxy(
                        f"{ODOO_URL}/xmlrpc/2/object",
                        transport=_PingTransport(timeout=10.0),
                    )
                    cls._models = _LockingProxy(raw_models, cls._lock)
                    cls._uid    = uid

    @classmethod
    def reset(cls):
        cls._uid    = None
        cls._models = None


def _download_invoice_pdf(models, uid, invoice_id: int, invoice_name: str, report_id: int) -> Path | None:
    """Web-session login + /report/pdf download. None on any failure. Ported from
    test_odoo_counter_app.py (KAN-70/71 prototype); report_id is config-driven here
    instead of a hardcoded module constant (KAN-47)."""
    try:
        with requests.Session() as session:
            resp = session.post(
                f"{ODOO_URL}/web/session/authenticate",
                json={
                    'jsonrpc': '2.0', 'method': 'call',
                    'params': {'db': ODOO_DB, 'login': ODOO_USER, 'password': ODOO_PASSWORD},
                },
                timeout=30,
            )
            result = resp.json().get('result')
            if not result or not result.get('uid'):
                return None

            reports = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'ir.actions.report', 'read',
                [[report_id]],
                {'fields': ['report_name', 'model']}
            )
            if not reports:
                return None
            if reports[0].get('model') != 'account.move':
                return None
            report_name = reports[0]['report_name']

            r = session.get(f"{ODOO_URL}/report/pdf/{report_name}/{invoice_id}", timeout=60)
            if r.status_code != 200 or 'pdf' not in r.headers.get('Content-Type', '').lower():
                return None

            out_dir = _get_base_dir() / 'invoices'
            out_dir.mkdir(exist_ok=True)
            safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in invoice_name)
            path = out_dir / f"{safe_name}_{report_id}.pdf"
            path.write_bytes(r.content)
            return path
    except Exception as e:
        print(f"[Invoice] ดาวน์โหลดไม่สำเร็จ: {e}", flush=True)
        return None


THAI_BAHT_WORDING_ACTION_NAME = 'ใส่คำอ่าน ไทยบาท by feng'


def _create_and_post_invoice(models, uid, sale_order_id: int) -> list | None:
    """Auto-invoice creation: sale order has zero invoices — create one via Odoo's standard
    "Create Invoice" wizard (sale.advance.payment.inv, same path the UI button uses) and post it
    immediately so it has a real tax invoice number and can be printed. Returns new invoice_ids,
    or None on failure. Posted invoices are legally final in Odoo — see docs/adr/0003 and
    docs/adr/0004."""
    try:
        ctx = {'active_model': 'sale.order', 'active_ids': [sale_order_id], 'active_id': sale_order_id}
        wizard_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'sale.advance.payment.inv', 'create',
            [{'advance_payment_method': 'delivered'}],  # 'delivered' = "Regular invoice", not down payment
            {'context': ctx}
        )
        new_invoice_ids = _run_create_invoices_with_recovery(models, uid, sale_order_id, wizard_id, ctx)
        if not new_invoice_ids:
            raise RuntimeError("Odoo ไม่สร้างใบกำกับภาษีให้ (ไม่มีรายการที่ invoice ได้)")
        _link_sale_order_on_invoice(models, uid, new_invoice_ids, sale_order_id)
        _apply_thai_baht_wording(models, uid, new_invoice_ids)
        _post_invoices_with_recovery(models, uid, new_invoice_ids)
        return new_invoice_ids
    except Exception as e:
        print(f"[Invoice] สร้าง/post ใบกำกับภาษีไม่สำเร็จ (sale order {sale_order_id}): {e}", flush=True)
        return None


def _run_create_invoices_with_recovery(models, uid, sale_order_id: int, wizard_id: int, ctx: dict) -> list:
    """Call the wizard's create_invoices; if the RPC response itself fails to marshal, re-read
    invoice_ids to check whether the invoice was actually created before giving up."""
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'sale.advance.payment.inv', 'create_invoices',
            [[wizard_id]], {'context': ctx}
        )
    except Exception as e:
        print(f"[Invoice] create_invoices RPC error — เช็คซ้ำว่าสร้างสำเร็จจริงไหม: {e}", flush=True)
    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, 'sale.order', 'read',
        [[sale_order_id]], {'fields': ['invoice_ids']}
    )
    return orders[0].get('invoice_ids') or []


def _post_invoices_with_recovery(models, uid, invoice_ids: list):
    """Call action_post; if the RPC response fails to marshal, re-read the invoice state before
    re-raising — the post may have actually succeeded server-side."""
    try:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'action_post', [invoice_ids])
    except Exception:
        print(f"[Invoice] action_post RPC error — เช็คซ้ำสถานะจริงก่อนยอมแพ้", flush=True)
        invoices = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'read',
            [invoice_ids], {'fields': ['state']}
        )
        if any(inv['state'] != 'posted' for inv in invoices):
            raise


def _apply_thai_baht_wording(models, uid, invoice_ids: list):
    """Run the Thai-baht wording server action against draft customer invoices."""
    action_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, 'ir.actions.server', 'search',
        [[
            ['name', '=', THAI_BAHT_WORDING_ACTION_NAME],
            ['model_id.model', '=', 'account.move'],
        ]],
        {'limit': 1}
    )
    if not action_ids:
        raise RuntimeError(f'ไม่พบ Odoo action: {THAI_BAHT_WORDING_ACTION_NAME}')
    context = {
        'active_model': 'account.move',
        'active_ids': invoice_ids,
        'active_id': invoice_ids[0],
    }
    models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, 'ir.actions.server', 'run',
        [action_ids], {'context': context}
    )


def _link_sale_order_on_invoice(models, uid, invoice_ids: list, sale_order_id: int):
    """Stamp x_studio_sale_order_id on draft invoices before wording and posting.

    This write is required because the downstream server action depends on it.
    """
    models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'write',
        [invoice_ids, {'x_studio_sale_order_id': sale_order_id}]
    )


# ── Worker: ค้นหา picking จาก barcode ───────────────────────
class BarcodeWorker(QThread):
    data_ready         = pyqtSignal(dict)
    not_found          = pyqtSignal(str)
    error_occurred     = pyqtSignal(str)
    origin_ready       = pyqtSignal(str, object)  # fire ทันทีที่เจอ picking ใน Odoo (มี/ไม่มีสินค้า 3g ก็ส่ง)
    invoice_job_ready  = pyqtSignal(int, str)     # sale_order_id, picking_name — independent of origin/3g-move outcome

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
                {'fields': ['name', 'x_studio_tracking_no', 'partner_id', 'state', 'origin', 'sale_id'], 'limit': 1}
            )
            if not pickings:
                self.not_found.emit(self.barcode)
                return

            picking = pickings[0]
            origin = (picking.get('origin') or '').strip() if isinstance(picking.get('origin'), str) else ''
            shop = None
            sale_id = picking.get('sale_id')
            try:
                if isinstance(sale_id, (list, tuple)) and sale_id and isinstance(sale_id[0], int):
                    sale = models.execute_kw(
                        ODOO_DB, uid, ODOO_PASSWORD,
                        'sale.order', 'read', [[sale_id[0]]],
                        {'fields': [SHOP_IDENTITY_FIELD]}
                    )
                    if sale:
                        value = sale[0].get(SHOP_IDENTITY_FIELD)
                        if isinstance(value, (list, tuple)) and len(value) >= 2 and isinstance(value[0], int):
                            name = str(value[1] or '').strip()
                            if name:
                                shop = {'id': value[0], 'name': name}
                        elif isinstance(value, str) and value.strip():
                            shop = {'id': 0, 'name': value.strip()}
            except Exception:
                pass
            if origin:
                self.origin_ready.emit(origin, shop)
            # Invoice trigger (KAN-47): independent of origin being blank and of the
            # 3g-move check below — fires whenever the picking has a sale order at all.
            if isinstance(sale_id, (list, tuple)) and sale_id and isinstance(sale_id[0], int):
                self.invoice_job_ready.emit(sale_id[0], picking['name'])

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

            # ดึงเลข lot + วันหมดอายุ จาก stock.move.line — แยกตาม product
            move_ids = [m['id'] for m in moves]
            lots_by_product: dict = {}
            try:
                move_lines = models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    'stock.move.line', 'search_read',
                    [[['move_id', 'in', move_ids]]],
                    {'fields': ['product_id', 'lot_id', 'lot_name', 'quantity']}
                )

                # รวบรวม lot_id ทั้งหมดเพื่อดึง expiration_date ทีเดียว
                lot_ids = list({ml['lot_id'][0] for ml in move_lines if ml.get('lot_id')})
                lot_info: dict = {}
                if lot_ids:
                    # Odoo 15+ ใช้ stock.lot, รุ่นเก่าใช้ stock.production.lot
                    for model_name in ('stock.lot', 'stock.production.lot'):
                        try:
                            lot_recs = models.execute_kw(
                                ODOO_DB, uid, ODOO_PASSWORD,
                                model_name, 'read',
                                [lot_ids],
                                {'fields': ['name', 'expiration_date']}
                            )
                            for lr in lot_recs:
                                lot_info[lr['id']] = {
                                    'name': lr.get('name') or '',
                                    'expiration_date': lr.get('expiration_date') or '',
                                }
                            break
                        except Exception:
                            continue

                for ml in move_lines:
                    pid = ml['product_id'][0] if ml.get('product_id') else None
                    if pid is None:
                        continue
                    if ml.get('lot_id'):
                        info = lot_info.get(ml['lot_id'][0], {})
                        name = (info.get('name') or ml['lot_id'][1] or '').strip()
                        exp  = info.get('expiration_date') or ''
                    else:
                        name = (ml.get('lot_name') or '').strip()
                        exp  = ''
                    if not name:
                        continue
                    qty = ml.get('quantity') or 0.0
                    bucket = lots_by_product.setdefault(pid, [])
                    existing = next((b for b in bucket if b['name'] == name), None)
                    if existing:
                        existing['qty'] += qty
                    else:
                        bucket.append({'name': name, 'expiration_date': exp, 'qty': qty})
            except Exception as e:
                print(f"[Lot] lookup failed, showing no lot info: {e}", flush=True)

            self.data_ready.emit({'picking': picking, 'moves': moves, 'lots_by_product': lots_by_product})

        except Exception as e:
            OdooConn.reset()
            self.error_occurred.emit(str(e))


def _print_pdf_via_sumatra(sumatra_path: str, printer: str, pdf_path) -> None:
    """The one SumatraPDF silent-print invocation, shared by InvoicePrintWorker (real
    invoices) and CropSettingsDialog's Test Print button (KAN-50) — extracted so both call
    sites are provably identical rather than two parallel reimplementations."""
    subprocess.run(
        [sumatra_path, '-print-to', printer, '-silent', str(pdf_path)],
        check=True, timeout=30
    )


def _render_test_print_pdf() -> Path:
    """Renders a small one-page test PDF via QPrinter/QPainter (KAN-50), for the settings
    dialog's Test Print button. Written under tempfile's directory — deliberately not
    invoices/, which is reserved for downloaded customer invoices (KAN-47)."""
    fd, tmp_name = tempfile.mkstemp(suffix='.pdf', prefix='odoo_counter_test_print_')
    os.close(fd)
    path = Path(tmp_name)
    printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    painter = QPainter(printer)
    try:
        painter.drawText(200, 200, "AI นับซอง — Test Print")
        painter.drawText(200, 260, f"เวลา: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    finally:
        painter.end()
    return path


# ── Worker: พิมพ์ใบกำกับภาษีอัตโนมัติ (invoice auto-print, KAN-47) ──
class InvoicePrintWorker(QThread):
    print_status = pyqtSignal(str, str)  # ('ok'|'checking'|'warn'), message

    def __init__(self, sale_order_id: int, picking_name: str):
        super().__init__()
        self.sale_order_id = sale_order_id
        self.picking_name  = picking_name

    def run(self):
        try:
            cfg = _load_invoice_config()
            printer = cfg['printer_name']
            if not printer:
                self.print_status.emit('warn', 'ยังไม่ได้ตั้งค่าเครื่องพิมพ์ใบเสร็จ')
                print(f"[Invoice] {self.picking_name}: printer not configured, skip", flush=True)
                return
            if printer not in QPrinterInfo.availablePrinterNames():
                # KAN-50: configured printer was removed/renamed — pause and warn instead of
                # silently falling back to a different printer.
                self.print_status.emit('warn', f'ไม่พบเครื่องพิมพ์ "{printer}" ในระบบ — ตรวจสอบใน settings')
                print(f"[Invoice] {self.picking_name}: configured printer '{printer}' not available, skip", flush=True)
                return

            OdooConn.ensure()
            uid, models = OdooConn._uid, OdooConn._models

            orders = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'sale.order', 'read',
                [[self.sale_order_id]],
                {'fields': [cfg['need_bill_field'], 'invoice_ids']}
            )
            if not orders:
                print(f"[Invoice] {self.picking_name}: sale order not found, skip", flush=True)
                return

            need_bill_field = orders[0].get(cfg['need_bill_field'])
            need_bill = need_bill_field[1] if isinstance(need_bill_field, (list, tuple)) else (need_bill_field or '')
            documents = _resolve_documents_to_print(need_bill, cfg)
            if not documents:
                print(f"[Invoice] {self.picking_name}: need-bill flag not set, skip", flush=True)
                return

            invoice_ids = orders[0].get('invoice_ids') or []
            if not invoice_ids:
                if not cfg['auto_create_enabled']:
                    self.print_status.emit('warn', f'{self.picking_name}: ยังไม่มีใบกำกับภาษี')
                    return
                self.print_status.emit('checking', f'{self.picking_name}: กำลังสร้างใบกำกับภาษี...')
                invoice_ids = _create_and_post_invoice(models, uid, self.sale_order_id)
                if not invoice_ids:
                    self.print_status.emit('warn', f'{self.picking_name}: สร้างใบกำกับภาษีไม่สำเร็จ')
                    return

            invoices = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'account.move', 'search_read',
                [[['id', 'in', invoice_ids], ['move_type', '=', 'out_invoice'], ['state', '=', 'posted']]],
                {'fields': ['name'], 'limit': 1, 'order': 'id desc'}
            )
            if not invoices:
                self.print_status.emit('warn', f'{self.picking_name}: ไม่มีใบกำกับภาษีที่ post แล้ว')
                return
            invoice_name = invoices[0]['name']

            printed = []
            for report_id, label in documents:
                self.print_status.emit('checking', f'กำลังดึง {label} ({invoice_name})...')
                path = _download_invoice_pdf(models, uid, invoices[0]['id'], invoice_name, report_id)
                if not path:
                    self.print_status.emit(
                        'warn',
                        f'{self.picking_name}: พิมพ์ไปแล้ว {len(printed)}/{len(documents)} ฉบับ — ดึง {label} ไม่สำเร็จ'
                    )
                    return
                try:
                    _print_pdf_via_sumatra(cfg['sumatra_path'], printer, path)
                except Exception as e:
                    self.print_status.emit(
                        'warn',
                        f'{self.picking_name}: พิมพ์ไปแล้ว {len(printed)}/{len(documents)} ฉบับ — พิมพ์ {label} ไม่สำเร็จ ({e})'
                    )
                    print(f"[Invoice] {self.picking_name}: print failed for {label} — {e}", flush=True)
                    return
                printed.append(label)

            suffix = f' ({" + ".join(printed)})' if len(printed) > 1 else ''
            self.print_status.emit('ok', f'พิมพ์ใบเสร็จ {invoice_name} แล้ว{suffix}')
            print(f"[Invoice] {self.picking_name}: printed {invoice_name} ({', '.join(printed)})", flush=True)

        except Exception as e:
            OdooConn.reset()
            self.print_status.emit('warn', f'{self.picking_name}: {e}')
            print(f"[Invoice] {self.picking_name}: error — {e}", flush=True)


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


# ── Worker: ตรวจสถานะการเชื่อมต่อ Odoo เป็นช่วงๆ ─────────────
class _PingTransport(xmlrpc.client.SafeTransport):
    """SafeTransport ที่มี connection timeout — กัน UI ค้างเวลา network ขาด"""
    def __init__(self, timeout: float = 5.0):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class OdooStatusWorker(QThread):
    status_changed = pyqtSignal(str, str)  # state: 'ok'|'fail'|'checking', message

    _INTERVAL_S   = 30
    _PING_TIMEOUT = 5

    def __init__(self):
        super().__init__()
        self._running = True
        self._wake    = threading.Event()

    def stop(self):
        self._running = False
        self._wake.set()

    def check_now(self):
        self._wake.set()

    def run(self):
        while self._running:
            self.status_changed.emit('checking', 'กำลังตรวจสอบ...')
            try:
                proxy = xmlrpc.client.ServerProxy(
                    f"{ODOO_URL}/xmlrpc/2/common",
                    transport=_PingTransport(timeout=self._PING_TIMEOUT),
                )
                ver = proxy.version()
                sv  = ver.get('server_version', '?') if isinstance(ver, dict) else '?'
                self.status_changed.emit('ok', f"เชื่อมต่อแล้ว ({sv})")
            except Exception as e:
                OdooConn.reset()
                err = str(e)
                if len(err) > 70:
                    err = err[:67] + '...'
                self.status_changed.emit('fail', f"เชื่อมต่อไม่ได้ — {err}")

            self._wake.wait(self._INTERVAL_S)
            self._wake.clear()


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

    # VK → ASCII: bypass IME ทุกภาษา
    _VK_MAP: dict = {
        **{vk: chr(vk) for vk in range(ord('A'), ord('Z') + 1)},   # 65-90 → A-Z
        **{vk: str(vk - 48) for vk in range(48, 58)},              # 48-57 → 0-9
        **{vk: str(vk - 96) for vk in range(96, 106)},             # 96-105 → numpad 0-9
        189: '-', 109: '-',   # minus / numpad minus
        191: '/', 111: '/',   # slash / numpad slash
        190: '.', 110: '.',   # period / numpad period
    }

    def _on_press(self, key):
        if not self._active or self._suppress:
            return
        now = time.monotonic()
        if now - self._last_time > self._TIMEOUT:
            self._buffer = []
        self._last_time = now

        if key == pynput_kb.Key.enter:
            barcode = ''.join(self._buffer)
            self._buffer = []
            self.buffer_updated.emit('')
            if len(barcode) >= 4:
                self.barcode_ready.emit(barcode)
            return
        if key == pynput_kb.Key.backspace and self._buffer:
            self._buffer.pop()
            self.buffer_updated.emit(''.join(self._buffer))
            return

        vk = getattr(key, 'vk', None)
        char = self._VK_MAP.get(vk) if vk is not None else None
        if char:
            self._buffer.append(char)
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
_KEYWORD_ODOO_NAME = {
    'excellent': 'Excellent Rich 95% 3.1g',
    'medium':    'Medium Rich 95% 3.1g',
    'classic':   'Classic Rich 95% 3.1g',
    'houjicha':  'Houjicha Rich 95% 3.1g',
    'genmaicha': 'Genmaicha Powder 3 g',
}

_FULL_CROP = (0.0, 0.0, 1.0, 1.0)

def _draw_obb(frame: np.ndarray, res, names: dict, crop_rect: tuple = _FULL_CROP):
    """Crop frame to counting zone, draw OBBs of detections inside, return (cropped_annotated, counts).

    Model already ran on the full frame; we filter by center-inside-crop and
    return the cropped region so the display zooms into the counting zone.
    """
    counts: dict[str, int] = {}
    H, W = frame.shape[:2]
    cx, cy, cw, ch = crop_rect
    rx, ry = int(cx * W), int(cy * H)
    rw, rh = max(1, int(cw * W)), max(1, int(ch * H))

    out = frame[ry:ry + rh, rx:rx + rw].copy()

    if res.obb is not None and len(res.obb) > 0:
        pts_all = res.obb.xyxyxyxy.cpu().numpy()
        centers = pts_all.mean(axis=1)
        for i, cls_idx in enumerate(res.obb.cls.tolist()):
            x_c, y_c = centers[i]
            if not (rx <= x_c < rx + rw and ry <= y_c < ry + rh):
                continue
            pts_translated = pts_all[i].copy()
            pts_translated[:, 0] -= rx
            pts_translated[:, 1] -= ry
            pts_int = pts_translated.astype(int)
            name  = names[int(cls_idx)]
            color = next((c for kw, c in _OBB_COLORS.items() if kw in name.lower()), (200, 200, 200))
            cv2.polylines(out, [pts_int], isClosed=True, color=color, thickness=3)
            counts[name] = counts.get(name, 0) + 1

    return out, counts


# ── Worker: กล้อง + YOLO inference ─────────────────────────
class CameraWorker(QThread):
    frame_ready        = pyqtSignal(QImage, object)
    status_message     = pyqtSignal(str)
    model_ready        = pyqtSignal(str)
    camera_error       = pyqtSignal(str)
    image_infer_done   = pyqtSignal(QImage, object)
    image_infer_error  = pyqtSignal(str)
    raw_frame_ready    = pyqtSignal(QImage)  # ส่งภาพ pre-inference สำหรับหน้า crop settings

    def __init__(self, model_path: str, camera_id: int = 0, conf: float | None = None):
        super().__init__()
        self.model_path = model_path
        self.camera_id  = camera_id
        self.conf       = conf if conf is not None else _load_conf()
        self._running   = True
        self._img_req   = queue.Queue(maxsize=1)
        self._crop_rect: tuple = _load_crop()
        self._emit_raw: bool   = False
        self._inference_enabled: bool = False
        self._last_raw_frame = None

    def infer_image(self, image_path: str):
        try:
            self._img_req.put_nowait(image_path)
        except queue.Full:
            pass

    def set_crop_rect(self, rect: tuple):
        self._crop_rect = rect

    def set_conf(self, conf: float):
        self.conf = max(0.05, min(0.95, float(conf)))

    def set_emit_raw(self, enabled: bool):
        self._emit_raw = enabled

    def set_inference_enabled(self, enabled: bool):
        self._inference_enabled = enabled

    def save_snapshot(self, folder: Path, filename: str):
        frame = self._last_raw_frame
        if frame is None:
            return
        def _write():
            try:
                folder.mkdir(exist_ok=True)
                cv2.imwrite(str(folder / filename), frame)
            except Exception as e:
                print(f"[Snapshot] บันทึกไม่สำเร็จ: {e}", flush=True)
        threading.Thread(target=_write, daemon=True).start()

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
        self.status_message.emit(f"โหลด {loaded_name} สำเร็จ — กำลัง warmup...")
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        for _ in range(5):
            model(dummy, verbose=False)
        self.status_message.emit(f"โหลด {loaded_name} สำเร็จ — กำลังเปิดกล้อง...")

        # MSMF (Media Foundation) ใช้ Windows Frame Server — แชร์กล้องกับ OBS/แอปอื่นได้
        cap = cv2.VideoCapture(self.camera_id, cv2.CAP_MSMF)
        if not cap.isOpened():
            print("[Camera] MSMF เปิดไม่ได้ — fallback เป็น default backend", flush=True)
            cap = cv2.VideoCapture(self.camera_id)
        if not cap.isOpened():
            self.camera_error.emit(
                f"เปิดกล้องไม่ได้ (camera_id={self.camera_id}) — เช็คสาย/driver หรือโปรแกรมอื่นที่ใช้กล้องอยู่"
            )
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.status_message.emit(f"โหลด {loaded_name} สำเร็จ — รอสแกน Barcode")
        self.model_ready.emit(loaded_name)

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
                        # ภาพอัพโหลดไม่ใช้ crop (ผู้ใช้เลือกรูปเอง — นับทั้งภาพ)
                        annotated, cc = _draw_obb(img_frame, res, model.names)
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
                    # 1) crop center ตาม orientation: landscape→16:9, portrait→9:16
                    is_landscape = w >= h
                    target = (16 / 9) if is_landscape else (9 / 16)
                    current = w / h
                    if current > target:
                        new_w = int(round(h * target))
                        x     = (w - new_w) // 2
                        frame = frame[:, x:x + new_w]
                    elif current < target:
                        new_h = int(round(w / target))
                        y     = (h - new_h) // 2
                        frame = frame[y:y + new_h, :]
                    # 2) downscale ให้ด้านยาวไม่เกิน 1920, ด้านสั้นไม่เกิน 1080
                    fh, fw = frame.shape[:2]
                    if is_landscape and fh > 1080:
                        frame = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
                    elif not is_landscape and fw > 1080:
                        frame = cv2.resize(frame, (1080, 1920), interpolation=cv2.INTER_AREA)

                    # emit raw frame (post-preprocess) สำหรับหน้า crop settings
                    if self._emit_raw:
                        rgb_raw = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        rh, rw, rch = rgb_raw.shape
                        rqimg = QImage(rgb_raw.data, rw, rh, rch * rw, QImage.Format.Format_RGB888).copy()
                        self.raw_frame_ready.emit(rqimg)

                    if not self._inference_enabled:
                        continue

                    self._last_raw_frame = frame
                    t0    = time.perf_counter()
                    res   = model(frame, conf=self.conf, verbose=False)[0]
                    ms    = (time.perf_counter() - t0) * 1000
                    annotated, cc = _draw_obb(frame, res, model.names, self._crop_rect)
                    fps = 1000 / ms if ms > 0 else 0
                    print(f"[Detect] {ms:.1f} ms  |  {fps:.1f} FPS  |  {cc}", flush=True)
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

            # ถ้าไม่มี consumer (inference ปิด + ไม่มี crop preview) ข้าม push เพื่อประหยัด CPU
            if self._inference_enabled or self._emit_raw:
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


# ── Crop settings UI ─────────────────────────────────────
class CropPreviewWidget(QWidget):
    """ลากเมาส์เพื่อกำหนดสี่เหลี่ยมพื้นที่นับ ค่า rect เก็บเป็น ratio 0..1"""
    rectChanged = pyqtSignal(tuple)

    def __init__(self):
        super().__init__()
        self._qimg: QImage | None = None
        self._rect: tuple = _FULL_CROP
        self._dragging = False
        self._drag_start: tuple | None = None
        self.setMinimumSize(720, 405)
        self.setStyleSheet("background:#0e0e14; border-radius:6px;")

    def set_frame(self, qimg: QImage):
        self._qimg = qimg
        self.update()

    def set_rect(self, rect: tuple):
        self._rect = rect
        self.update()

    def get_rect(self) -> tuple:
        return self._rect

    def _img_geom(self):
        if self._qimg is None or self._qimg.isNull():
            return (0, 0, self.width(), self.height())
        iw, ih = self._qimg.width(), self._qimg.height()
        if iw <= 0 or ih <= 0:
            return (0, 0, self.width(), self.height())
        scale = min(self.width() / iw, self.height() / ih)
        dw, dh = int(iw * scale), int(ih * scale)
        dx, dy = (self.width() - dw) // 2, (self.height() - dh) // 2
        return (dx, dy, dw, dh)

    def _to_norm(self, px: float, py: float):
        ix, iy, iw, ih = self._img_geom()
        if iw <= 0 or ih <= 0:
            return None
        nx = max(0.0, min(1.0, (px - ix) / iw))
        ny = max(0.0, min(1.0, (py - iy) / ih))
        return (nx, ny)

    def mousePressEvent(self, e):
        n = self._to_norm(e.position().x(), e.position().y())
        if n is None:
            return
        self._dragging   = True
        self._drag_start = n
        self._rect = (n[0], n[1], 0.0, 0.0)
        self.update()

    def mouseMoveEvent(self, e):
        if not self._dragging or self._drag_start is None:
            return
        n = self._to_norm(e.position().x(), e.position().y())
        if n is None:
            return
        x0, y0 = self._drag_start
        x1, y1 = n
        rx, ry = min(x0, x1), min(y0, y1)
        rw, rh = abs(x1 - x0), abs(y1 - y0)
        self._rect = (rx, ry, rw, rh)
        self.update()

    def mouseReleaseEvent(self, e):
        if not self._dragging:
            return
        self._dragging = False
        x, y, w, h = self._rect
        if w < 0.05 or h < 0.05:
            # เล็กเกินไป — ถือว่ายังไม่เลือก
            self._rect = _FULL_CROP
        else:
            x = max(0.0, min(1.0 - w, x))
            y = max(0.0, min(1.0 - h, y))
            self._rect = (x, y, w, h)
        self.rectChanged.emit(self._rect)
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(14, 14, 20))
        if self._qimg is None or self._qimg.isNull():
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "รอ frame จากกล้อง...")
            return
        ix, iy, iw, ih = self._img_geom()
        painter.drawImage(QRect(ix, iy, iw, ih), self._qimg)
        x, y, w, h = self._rect
        rx = ix + int(x * iw); ry = iy + int(y * ih)
        rw = int(w * iw);      rh = int(h * ih)
        # มืดส่วนนอกกรอบ
        overlay = QColor(0, 0, 0, 130)
        painter.fillRect(ix, iy, iw, ry - iy, overlay)
        painter.fillRect(ix, ry + rh, iw, iy + ih - (ry + rh), overlay)
        painter.fillRect(ix, ry, rx - ix, rh, overlay)
        painter.fillRect(rx + rw, ry, ix + iw - (rx + rw), rh, overlay)
        # เส้นขอบกรอบสีเหลือง
        pen = QPen(QColor(0, 220, 220))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(rx, ry, rw, rh)


class CropSettingsDialog(QDialog):
    def __init__(self, current_rect: tuple, current_conf: float, current_printer: str = '', current_auto_print: bool = True, current_auto_create: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ตั้งค่ากล้อง / Detection")
        self.resize(960, 720)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        info = QLabel(
            "ลากเมาส์บนภาพเพื่อกำหนดพื้นที่ \"counting zone\" — "
            "เฉพาะของที่อยู่ในกรอบจะถูกนับ  •  ภาพเข้า model ยังคง 1080p เต็มเหมือนเดิม"
        )
        info.setStyleSheet("color:#aaa; font-size:13px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.preview = CropPreviewWidget()
        self.preview.set_rect(current_rect)
        self.preview.rectChanged.connect(self._on_rect_changed)
        layout.addWidget(self.preview, 1)

        self.lbl_info = QLabel(self._rect_text(current_rect))
        self.lbl_info.setStyleSheet("color:#ccc; font-size:12px; padding:4px;")
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_info)

        # ── Confidence threshold ──────────────────────────
        conf_box = QGroupBox("Confidence Threshold (เกณฑ์ความมั่นใจของ detect)")
        conf_box.setStyleSheet(
            "QGroupBox { color:#aaa; font-size:12px; border:1px solid #333;"
            "border-radius:6px; margin-top:8px; padding-top:8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 6px; }"
        )
        cl = QHBoxLayout(conf_box)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(10)

        self._conf = max(0.05, min(0.95, float(current_conf)))
        self.conf_slider = QSlider(Qt.Orientation.Horizontal)
        self.conf_slider.setRange(5, 95)  # 0.05–0.95
        self.conf_slider.setValue(int(round(self._conf * 100)))
        self.conf_slider.setSingleStep(1)
        self.conf_slider.setTickInterval(10)
        self.conf_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.conf_slider.valueChanged.connect(self._on_conf_changed)

        self.lbl_conf = QLabel(self._conf_text(self._conf))
        self.lbl_conf.setStyleSheet("color:#90CAF9; font-size:14px; font-weight:bold; min-width:130px;")
        self.lbl_conf.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cl.addWidget(QLabel("ต่ำ (จับเยอะ)"), 0)
        cl.addWidget(self.conf_slider, 1)
        cl.addWidget(QLabel("สูง (เข้มงวด)"), 0)
        cl.addWidget(self.lbl_conf, 0)
        layout.addWidget(conf_box)

        # ── Invoice printer (KAN-50) ───────────────────────
        printer_box = QGroupBox("เครื่องพิมพ์ใบเสร็จ (Invoice Printer)")
        printer_box.setStyleSheet(
            "QGroupBox { color:#aaa; font-size:12px; border:1px solid #333;"
            "border-radius:6px; margin-top:8px; padding-top:8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 6px; }"
        )
        pv = QVBoxLayout(printer_box)
        pv.setContentsMargins(12, 10, 12, 10)
        pv.setSpacing(6)

        self.chk_auto_print = QCheckBox("เปิดใช้งานพิมพ์ใบเสร็จอัตโนมัติ")
        self.chk_auto_print.setChecked(current_auto_print)
        self.chk_auto_print.setStyleSheet("color:#eee; font-size:13px;")
        pv.addWidget(self.chk_auto_print)

        self.chk_auto_create = QCheckBox("อนุญาตให้สร้างใบกำกับภาษีอัตโนมัติ")
        self.chk_auto_create.setChecked(current_auto_create)
        self.chk_auto_create.setStyleSheet("color:#eee; font-size:13px;")
        pv.addWidget(self.chk_auto_create)

        pl = QHBoxLayout()
        pl.setSpacing(10)

        self.printer_combo = QComboBox()
        self._populate_printer_combo(current_printer)

        self.btn_test_print = QPushButton("พิมพ์ทดสอบ")
        self.btn_test_print.setFixedHeight(32)
        self.btn_test_print.setStyleSheet("background:#37474F; color:white; font-size:13px; border-radius:6px;")
        self.btn_test_print.clicked.connect(self._on_test_print)

        pl.addWidget(QLabel("เครื่องพิมพ์:"), 0)
        pl.addWidget(self.printer_combo, 1)
        pl.addWidget(self.btn_test_print, 0)
        pv.addLayout(pl)

        self.lbl_print_status = QLabel("")
        self.lbl_print_status.setStyleSheet("color:#ccc; font-size:12px;")
        pv.addWidget(self.lbl_print_status)

        layout.addWidget(printer_box)

        btn_row    = QHBoxLayout()
        btn_reset  = QPushButton("รีเซ็ตเต็มจอ")
        btn_cancel = QPushButton("ยกเลิก")
        btn_save   = QPushButton("บันทึก")
        for b in (btn_reset, btn_cancel, btn_save):
            b.setFixedHeight(38)
            b.setMinimumWidth(120)
        btn_save.setStyleSheet("background:#2E7D32; color:white; font-weight:bold; font-size:13px; border-radius:6px;")
        btn_cancel.setStyleSheet("background:#37474F; color:white; font-size:13px; border-radius:6px;")
        btn_reset.setStyleSheet("background:#37474F; color:white; font-size:13px; border-radius:6px;")
        btn_reset.clicked.connect(self._reset)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self.accept)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    @staticmethod
    def _rect_text(r: tuple) -> str:
        x, y, w, h = r
        return f"X: {x*100:.1f}%   Y: {y*100:.1f}%   W: {w*100:.1f}%   H: {h*100:.1f}%"

    @staticmethod
    def _conf_text(c: float) -> str:
        return f"conf = {c:.2f}"

    def _on_rect_changed(self, rect: tuple):
        self.lbl_info.setText(self._rect_text(rect))

    def _on_conf_changed(self, val: int):
        self._conf = val / 100.0
        self.lbl_conf.setText(self._conf_text(self._conf))

    def _reset(self):
        self.preview.set_rect(_FULL_CROP)
        self.lbl_info.setText(self._rect_text(_FULL_CROP))

    def update_frame(self, qimg: QImage):
        self.preview.set_frame(qimg)

    def get_rect(self) -> tuple:
        return self.preview.get_rect()

    def get_conf(self) -> float:
        return self._conf

    def _populate_printer_combo(self, current_printer: str):
        """Fills the dropdown from QPrinterInfo.availablePrinterNames() (KAN-50). Two
        deliberate non-obvious states:
        - not configured yet (current_printer == ''): a neutral placeholder item is
          pre-selected — the first real printer is never auto-selected as a default.
        - configured but no longer installed (current_printer set but absent from the
          available list): the configured name is still shown, pre-selected, and annotated
          so the operator can see what's configured before choosing a real one, instead of
          silently swapping to something else.
        """
        self.printer_combo.clear()
        available = QPrinterInfo.availablePrinterNames()
        self.printer_combo.addItem("-- ยังไม่เลือก --", "")
        for name in available:
            self.printer_combo.addItem(name, name)
        if current_printer:
            if current_printer in available:
                idx = self.printer_combo.findData(current_printer)
            else:
                self.printer_combo.addItem(f"{current_printer}  (ไม่พบเครื่องพิมพ์นี้ในระบบ)", current_printer)
                idx = self.printer_combo.count() - 1
            self.printer_combo.setCurrentIndex(idx)
        else:
            self.printer_combo.setCurrentIndex(0)

    def get_printer(self) -> str:
        return self.printer_combo.currentData() or ''

    def get_auto_print_enabled(self) -> bool:
        return self.chk_auto_print.isChecked()

    def get_auto_create_enabled(self) -> bool:
        return self.chk_auto_create.isChecked()

    def _on_test_print(self):
        printer = self.get_printer()
        if not printer:
            self.lbl_print_status.setText("กรุณาเลือกเครื่องพิมพ์ก่อนพิมพ์ทดสอบ")
            self.lbl_print_status.setStyleSheet("color:#FFB300; font-size:12px;")
            return
        pdf_path = None
        try:
            cfg = _load_invoice_config()
            pdf_path = _render_test_print_pdf()
            _print_pdf_via_sumatra(cfg['sumatra_path'], printer, pdf_path)
            self.lbl_print_status.setText(f"ส่งพิมพ์ทดสอบไปที่ {printer} แล้ว")
            self.lbl_print_status.setStyleSheet("color:#66BB6A; font-size:12px;")
        except Exception as e:
            self.lbl_print_status.setText(f"พิมพ์ทดสอบล้มเหลว: {e}")
            self.lbl_print_status.setStyleSheet("color:#EF5350; font-size:12px;")
        finally:
            if pdf_path is not None:
                pdf_path.unlink(missing_ok=True)


# ── หน้าต่างนับ (เด้งขึ้นเมื่อเจอ Excellent/Houjicha 3g) ────
class CounterPanel(QWidget):
    closed                 = pyqtSignal()
    image_infer_requested  = pyqtSignal(str)
    snapshot_requested     = pyqtSignal(str)  # picking_name

    # เส้น "Lot:" ต้องพอดีในการ์ดเสมอ ห้ามล้น (หน้างานจะได้ไม่ต้องเลื่อนจอ) — ไล่ลอง
    # ขนาดตัวอักษรจากใหญ่สุดไปเล็กสุดตามจำนวน lot จริงของสินค้านั้น ๆ ทุกครั้งที่ resize
    _LOT_FONT_SIZES = (13, 12, 11, 10, 9, 8)

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
        self._last_stable_counts: tuple = ()
        self._last_sound_status: str | None = None
        self._image_mode         = False
        self._save_workers: set  = set()
        self._pending_product_counts: list | None = None

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(1500)
        self._toast_timer.timeout.connect(self._hide_toast)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(1500)
        self._hide_timer.timeout.connect(self.hide)

        # MSN-style nudge: เขย่าหน้าต่างเมื่อนับผิด
        self._shake_timer = QTimer(self)
        self._shake_timer.timeout.connect(self._shake_step)
        self._shake_origin = None
        self._shake_offsets: list = []
        self._shake_idx = 0

        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── LEFT: Camera ─────────────────────────────────
        self.camera_label = QLabel("กำลังโหลดกล้อง...")
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setMinimumSize(560, 380)
        self.camera_label.setStyleSheet(
            "background:#1a1a1a; color:#666; font-size:15px; border-radius:8px;"
        )
        root.addWidget(self.camera_label, 1)

        self.lbl_toast = QLabel(self.camera_label)
        self.lbl_toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_toast.setWordWrap(True)
        self.lbl_toast.hide()

        self.lbl_alert = QLabel(self.camera_label)
        self.lbl_alert.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_alert.setWordWrap(True)
        self.lbl_alert.setStyleSheet(
            "background: rgba(183, 28, 28, 230); color: white;"
            "font-size: 16px; font-weight: bold;"
            "border: 2px solid #FF5252; border-radius: 8px; padding: 8px 14px;"
        )
        self.lbl_alert.hide()

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

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_inner = QWidget()
        self._cards_layout = QVBoxLayout(scroll_inner)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._cards_scroll.setWidget(scroll_inner)
        cb_layout.addWidget(self._cards_scroll)
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

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_upload = QPushButton("📁 อัพโหลด")
        self.btn_upload.setFixedHeight(42)
        self.btn_upload.setStyleSheet(
            "font-size:13px; background:#1565C0; color:white; border-radius:6px;"
        )
        self.btn_upload.clicked.connect(self._open_image)
        btn_row.addWidget(self.btn_upload, 1)

        self.btn_back_cam = QPushButton("📷 กลับกล้อง")
        self.btn_back_cam.setFixedHeight(42)
        self.btn_back_cam.setStyleSheet(
            "font-size:13px; background:#2E7D32; color:white; border-radius:6px;"
        )
        self.btn_back_cam.clicked.connect(self._back_to_camera)
        self.btn_back_cam.hide()
        btn_row.addWidget(self.btn_back_cam, 1)

        btn_close = QPushButton("ปิด — สแกนใบใหม่")
        btn_close.setFixedHeight(42)
        btn_close.setStyleSheet(
            "font-size:13px; background:#37474F; color:white; border-radius:6px;"
        )
        btn_close.clicked.connect(self.hide)
        btn_row.addWidget(btn_close, 1)

        right.addLayout(btn_row)

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
        self._build_count_table(entry['moves'], entry.get('lots_by_product') or {})

        self._fit_to_screen()
        self.show()
        self.activateWindow()
        self.raise_()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except Exception:
            pass

    def _fit_to_screen(self):
        """ปรับขนาดให้พอดีกับจอที่ใช้งานอยู่ (เว้น margin จาก taskbar/decoration)"""
        app = QApplication.instance()
        screen = app.screenAt(self.pos()) if self.isVisible() else None
        if screen is None:
            screen = app.primaryScreen()
        avail = screen.availableGeometry()

        # ใช้ 90% ของพื้นที่จอ แต่ไม่เกิน design size 1380×800
        target_w = min(1380, int(avail.width()  * 0.9))
        target_h = min(800,  int(avail.height() * 0.9))
        # minimum ให้ UI ยังใช้งานได้
        target_w = max(900,  target_w)
        target_h = max(560,  target_h)

        self.resize(target_w, target_h)
        # center บนจอที่เลือก
        x = avail.x() + (avail.width()  - target_w) // 2
        y = avail.y() + (avail.height() - target_h) // 2
        self.move(x, y)

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
        alert_lines: list[str] = []

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
                alert_lines.append(f"{pr['product_name']}: เกิน {cnt - demand}")
            else:
                color, stat = '#FF9800', f'ขาด {demand - cnt}'
                all_exact = False
                alert_lines.append(f"{pr['product_name']}: ขาด {demand - cnt}")

            pr['lbl_count'].setText(str(cnt))
            pr['lbl_count'].setStyleSheet(
                f"font-size:34px; color:{color}; font-weight:bold;"
            )
            pr['lbl_status'].setText(stat)
            pr['lbl_status'].setStyleSheet(
                f"background:{color}; color:white; font-size:13px; font-weight:bold;"
                f"border-radius:6px; padding:6px 12px;"
            )

        # ตรวจสอบสินค้าที่ detect ได้แต่ไม่อยู่ใน order — ถือเป็น "เกิน" เช่นกัน
        wrong: list[str] = []
        if self._product_rows:
            order_kws = {pr['keyword'] for pr in self._product_rows}
            wrong = [
                name for name, cnt in class_counts.items()
                if cnt > 0 and not any(kw in name.lower() for kw in order_kws)
            ]
            if wrong:
                all_exact   = False
                any_over    = True
                any_counted = True
                odoo_names = []
                for n in wrong:
                    kw = next((k for k in _KEYWORD_ODOO_NAME if k in n.lower()), None)
                    odoo_names.append(_KEYWORD_ODOO_NAME[kw] if kw else n)
                self.lbl_wrong.setText(f"⚠ พบสินค้าที่ไม่ใช่ใน Order: {', '.join(odoo_names)}")
                self.lbl_wrong.show()
                alert_lines.extend(f"{n}: ไม่อยู่ใน Order" for n in odoo_names)
            else:
                self.lbl_wrong.hide()

        # Persistent red alert: ขึ้นค้างไว้จนกว่าจะตรงตาม order
        if self._product_rows and any_counted and not all_exact:
            self._show_alert("✗ ไม่ตรงตาม Order\n" + "\n".join(alert_lines))
        else:
            self._hide_alert()

        # รวมจำนวนของนอก order เข้า stability key เพื่อให้ timer reset เมื่อจำนวนเปลี่ยน
        wrong_counts = {n: class_counts[n] for n in wrong}
        stability_key = (current_counts, wrong_counts)

        # Reset stability timer when counts change; clear last sound to allow re-notify
        if stability_key != self._last_stable_counts:
            self._stable_since       = now
            self._last_stable_counts = stability_key
            self._last_sound_status  = None

        if stable_check:
            if any_counted and self._stable_since is not None and now - self._stable_since >= 0.5:
                status_key = 'exact' if all_exact else ('over' if any_over else 'under')
                if status_key != self._last_sound_status:
                    self._last_sound_status = status_key
                    self._play_sound(status_key)
                    if status_key != 'exact':
                        self._shake_window()
                if all_exact and not self._log_posted:
                    self._log_posted = True
                    self._pending_product_counts = [
                        {
                            'product_name': pr['product_name'],
                            'counted':      self._get_count(self._last_class_counts, pr['keyword']),
                            'demand':       pr['demand'],
                        }
                        for pr in self._product_rows
                    ]
                    if self._current_entry:
                        self.snapshot_requested.emit(self._current_entry['picking']['name'])
                    self._show_toast("✓ ครบตามจำนวนใน order", success=True)
                    self._hide_timer.start()
        else:
            # Image mode — immediate result
            if any_counted:
                status_key = 'exact' if all_exact else ('over' if any_over else 'under')
                self._play_sound(status_key)
                if status_key != 'exact':
                    self._shake_window()
            if all_exact and not self._log_posted:
                self._log_posted = True
                self._pending_product_counts = [
                    {
                        'product_name': pr['product_name'],
                        'counted':      self._get_count(self._last_class_counts, pr['keyword']),
                        'demand':       pr['demand'],
                    }
                    for pr in self._product_rows
                ]
                self._show_toast("✓ ครบตามจำนวนใน order", success=True)
                self._hide_timer.start()

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

    def _shake_window(self):
        if self._shake_timer.isActive():
            self.move(self._shake_origin)
            self._shake_timer.stop()
        self._shake_origin = self.pos()
        # decay amplitude — แรงตอนแรก ค่อยๆ เบาลง คล้าย MSN nudge
        amps = [16, -14, 12, -10, 13, -11, 9, -7, 8, -6, 5, -4, 3, -2, 0]
        self._shake_offsets = [
            (a, (a // 3) if i % 2 == 0 else -(a // 3))
            for i, a in enumerate(amps)
        ]
        self._shake_idx = 0
        self._shake_timer.start(22)

    def _shake_step(self):
        if self._shake_idx >= len(self._shake_offsets):
            self._shake_timer.stop()
            if self._shake_origin is not None:
                self.move(self._shake_origin)
            return
        dx, dy = self._shake_offsets[self._shake_idx]
        self.move(self._shake_origin.x() + dx, self._shake_origin.y() + dy)
        self._shake_idx += 1

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
        self._hide_alert()

    @staticmethod
    def _get_count(class_counts: dict, keyword: str) -> int:
        for cls_name, cnt in class_counts.items():
            if keyword in cls_name.lower():
                return cnt
        return 0

    def _build_count_table(self, moves, lots_by_product: dict | None = None):
        self._product_rows            = []
        self._log_posted              = False
        self._stable_since            = None
        self._last_stable_counts      = ()
        self._last_sound_status       = None
        self._pending_product_counts  = None
        self.lbl_wrong.hide()
        self._hide_alert()

        while self._cards_layout.count() > 0:
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        lots_by_product = lots_by_product or {}
        for m in moves:
            pname   = self._strip_ref(m['product_id'][1])
            keyword = self._extract_keyword(pname)
            demand  = int(m['product_uom_qty'])
            pid     = m['product_id'][0] if m.get('product_id') else None
            lots    = lots_by_product.get(pid, [])
            row = self._create_product_card(pname, demand, lots)
            self._cards_layout.addWidget(row['card'])
            self._product_rows.append({
                'product_name': pname,
                'demand':       m['product_uom_qty'],
                'keyword':      keyword,
                **row,
            })
        self._cards_layout.addStretch(1)
        QTimer.singleShot(0, self._fit_cards_to_viewport)

    @staticmethod
    def _create_product_card(name: str, demand: int, lots: list | None = None):
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background:#252535; border-radius:8px; }"
        )
        card.setMinimumHeight(96)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 6, 10, 6)
        cl.setSpacing(1)

        lbl_name = QLabel(name)
        lbl_name.setStyleSheet("font-size:12px; color:#bbb; font-weight:bold;")
        lbl_name.setWordWrap(True)
        cl.addWidget(lbl_name)

        row = QHBoxLayout()
        row.setSpacing(6)

        lbl_count = QLabel("0")
        lbl_count.setStyleSheet("font-size:26px; color:#FF9800; font-weight:bold;")
        lbl_count.setAlignment(Qt.AlignmentFlag.AlignBottom)

        lbl_sep = QLabel(f"/ {demand}")
        lbl_sep.setStyleSheet("font-size:15px; color:#777;")
        lbl_sep.setAlignment(Qt.AlignmentFlag.AlignBottom)

        row.addWidget(lbl_count)
        row.addWidget(lbl_sep)
        row.addStretch(1)

        lbl_status = QLabel(f"ขาด {demand}")
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_status.setStyleSheet(
            "background:#FF9800; color:white; font-size:12px; font-weight:bold;"
            "border-radius:6px; padding:4px 10px;"
        )
        lbl_status.setMinimumWidth(85)
        row.addWidget(lbl_status)

        cl.addLayout(row)

        if lots:
            lot_lines = []
            for lot in lots:
                raw_name = lot['name']
                piece = raw_name[9:13] if len(raw_name) >= 13 else raw_name
                qty = lot.get('qty')
                if qty:
                    piece += f": {qty:g} ซอง"
                exp = (lot.get('expiration_date') or '').strip()
                ymd = exp.split(' ')[0] if exp else ''
                if ymd and ymd.count('-') == 2:
                    y, mo, d = ymd.split('-')
                    piece += f" (EXP {d}/{mo}/{y})"
                lot_lines.append(piece)
        else:
            lot_lines = ['-']

        # ข้อความ/ขนาดตัวอักษรจริงตั้งค่าทีหลังใน _fit_lot_label (ต้องรู้ความสูงการ์ดก่อน)
        lbl_lot = QLabel()
        lbl_lot.setWordWrap(True)
        cl.addWidget(lbl_lot)

        return {
            'card':       card,
            'lbl_count':  lbl_count,
            'lbl_status': lbl_status,
            'lbl_lot':    lbl_lot,
            'lot_lines':  lot_lines,
        }

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
        if not self._current_entry or not self._pending_product_counts:
            return
        product_counts = self._pending_product_counts
        self._pending_product_counts = None
        w = OdooSaveWorker(self._current_entry['picking']['id'], product_counts)
        w.save_error.connect(lambda msg: print(f"[Odoo] บันทึกไม่สำเร็จ: {msg}", flush=True))
        w.finished.connect(lambda: self._save_workers.discard(w))
        self._save_workers.add(w)
        w.start()

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

    def _show_alert(self, msg: str):
        self.lbl_alert.setText(msg)
        self._position_alert()
        self.lbl_alert.show()
        self.lbl_alert.raise_()

    def _hide_alert(self):
        self.lbl_alert.hide()

    def _position_alert(self):
        p = self.camera_label
        w = min(380, max(240, p.width() - 40))
        # word-wrap จะ wrap ที่ความกว้างนี้ — ใช้ heightForWidth
        inner_w = w - 28  # ลบ padding ใน stylesheet
        text_h = self.lbl_alert.fontMetrics().boundingRect(
            0, 0, inner_w, 10000,
            int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignCenter),
            self.lbl_alert.text()
        ).height()
        h = max(50, text_h + 20)
        x = (p.width() - w) // 2
        y = max(0, (p.height() - h) // 2)
        self.lbl_alert.setGeometry(x, y, w, h)

    def _fit_cards_to_viewport(self):
        if not self._product_rows:
            return
        slots = max(5, len(self._product_rows))
        vp_h = self._cards_scroll.viewport().height()
        spacing = self._cards_layout.spacing() * (slots - 1)
        card_h = max(96, (vp_h - spacing) // slots)

        # ความสูงที่ชื่อสินค้า + แถวจำนวน/สถานะกินไปแน่ ๆ (ฟอนต์คงที่ ไม่ขึ้นกับ card_h)
        # เหลือเท่าไหร่ถึงเป็นงบให้เส้น "Lot:" — ดู _create_product_card สำหรับ margin/spacing ที่อ้างถึง
        name_h = self._line_height_px(12)
        row_h  = max(self._line_height_px(34), self._line_height_px(13) + 12)  # steady-state sizes _apply_counts sets (34px count, 13px font + 12px padding status) — not the smaller build-time defaults, else the budget undercounts once counting starts
        overhead_h = name_h + row_h + 12 + 2  # margins แนวตั้ง (6+6) + spacing 2 ช่อง (1px*2)

        for pr in self._product_rows:
            pr['card'].setFixedHeight(card_h)
            self._fit_lot_label(pr, card_h - overhead_h)

    @staticmethod
    def _line_height_px(px: int) -> int:
        f = QFont()
        f.setPixelSize(px)
        return QFontMetrics(f).height()

    def _fit_lot_label(self, pr: dict, budget_h: int) -> None:
        """พอดีไม่ได้แม้ที่ font ต่ำสุด -> ตัดบรรทัดส่วนเกินเหลือ "+N lot" แทนล้นการ์ด"""
        lot_lines = pr['lot_lines']
        lbl_lot   = pr['lbl_lot']
        budget_h  = max(0, budget_h)

        font_px = self._LOT_FONT_SIZES[-1]
        for candidate in self._LOT_FONT_SIZES:
            if self._line_height_px(candidate) * len(lot_lines) <= budget_h:
                font_px = candidate
                break

        max_lines = max(1, budget_h // self._line_height_px(self._LOT_FONT_SIZES[-1]))
        if len(lot_lines) <= max_lines:
            shown = lot_lines
        elif max_lines == 1:
            shown = [f"{len(lot_lines)} lot (พื้นที่ไม่พอ)"]
        else:
            rest = len(lot_lines) - (max_lines - 1)
            shown = lot_lines[:max_lines - 1] + [f"+{rest} lot อื่น"]

        text = 'Lot: ' + shown[0]
        if len(shown) > 1:
            text += '\n' + '\n'.join('     ' + s for s in shown[1:])

        lbl_lot.setStyleSheet(f"font-size:{font_px}px; color:#80CBC4; font-weight:bold;")
        lbl_lot.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.lbl_alert.isVisible():
            self._position_alert()
        self._fit_cards_to_viewport()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._save_to_odoo()
        self.closed.emit()


# ── WebSocket bridge: broadcast barcodes to browser (Tampermonkey) ──
class BarcodeBridgeWorker(QObject):
    """WebSocket server ส่ง barcode ที่แอปสแกนได้ไปยัง Tampermonkey ใน browser
    (TikTok / Shopee / Odoo web). รันใน daemon thread แยก asyncio loop —
    Qt thread เรียก broadcast() ผ่าน run_coroutine_threadsafe.
    """

    PORT = 9999

    status_changed = pyqtSignal(str, str)  # state ∈ {"ok","fail","starting"}, message

    def __init__(self):
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set = set()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except OSError as e:
            self.status_changed.emit('fail', f"port {self.PORT} ถูกใช้แล้ว")
            print(f"[Bridge] bind fail: {e}")
        except Exception as e:
            self.status_changed.emit('fail', str(e)[:70])
            print(f"[Bridge] error: {e}")

    async def _serve(self):
        async with websockets.serve(self._handler, "localhost", self.PORT):
            self.status_changed.emit('ok', "พร้อม (0 tabs)")
            print(f"[Bridge] listening ws://localhost:{self.PORT}")
            await asyncio.Future()  # run until loop.stop()

    async def _handler(self, websocket):
        self._clients.add(websocket)
        self._emit_client_count()
        try:
            await websocket.wait_closed()
        finally:
            self._clients.discard(websocket)
            self._emit_client_count()

    def _emit_client_count(self):
        n = len(self._clients)
        self.status_changed.emit('ok', f"พร้อม ({n} tabs)")

    def broadcast(self, order: str, shop=None):
        """Call from Qt thread — schedules broadcast in asyncio loop."""
        if not self._loop or not self._loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_async(order, shop), self._loop)

    async def _broadcast_async(self, order: str, shop):
        payload = json.dumps({'order': order, 'platform': None, 'shop': shop})
        if not self._clients:
            print(f"[Bridge] no clients — order dropped: {order!r}")
            return
        await asyncio.gather(
            *[c.send(payload) for c in self._clients],
            return_exceptions=True,
        )
        print(f"[Bridge] sent {payload!r} → {len(self._clients)} client(s)")

    def stop(self):
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)


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
        self._invoice_queue: deque = deque()
        self._invoice_worker: InvoicePrintWorker | None = None

        self._barcode_listener = GlobalBarcodeListener()
        self._barcode_listener.barcode_ready.connect(self._on_barcode_scanned)
        self._barcode_listener.buffer_updated.connect(self._on_buffer_updated)
        self._barcode_listener.start()

        self._build_ui()
        self._start_camera()

        self._odoo_status_worker = OdooStatusWorker()
        self._odoo_status_worker.status_changed.connect(self._on_odoo_status)
        self._odoo_status_worker.start()

        self._bridge = BarcodeBridgeWorker()
        self._bridge.status_changed.connect(self._on_bridge_status)
        self._bridge.start()

        threading.Thread(target=self._preconnect_odoo, daemon=True).start()

        QApplication.instance().focusChanged.connect(self._on_app_focus_changed)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)

        bc_box = QGroupBox("Barcode Scanner")
        bc_outer = QVBoxLayout(bc_box)
        bc_outer.setContentsMargins(10, 6, 10, 6)
        bc_outer.setSpacing(4)

        bc_row = QHBoxLayout()

        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("พิมพ์หรือสแกน Barcode แล้วกด Enter  (ใช้ได้แม้ย่อ app ไว้)")
        self.barcode_input.setFixedHeight(40)
        self.barcode_input.setStyleSheet("font-size:15px; padding:4px 10px;")
        self.barcode_input.returnPressed.connect(self._on_returnpressed)

        self.lbl_bc_icon = QLabel("⬜")
        self.lbl_bc_icon.setFixedWidth(30)
        self.lbl_bc_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_bc_icon.setStyleSheet("font-size:20px;")

        self.btn_crop_settings = QPushButton("⚙")
        self.btn_crop_settings.setFixedSize(40, 40)
        self.btn_crop_settings.setToolTip("ตั้งค่า Crop กล้อง (counting zone)")
        self.btn_crop_settings.setStyleSheet(
            "font-size:18px; background:#37474F; color:white; border-radius:6px;"
        )
        self.btn_crop_settings.clicked.connect(self._open_crop_settings)

        bc_row.addWidget(self.barcode_input)
        bc_row.addWidget(self.lbl_bc_icon)
        bc_row.addWidget(self.btn_crop_settings)
        bc_outer.addLayout(bc_row)

        self.lbl_odoo_status = QLabel("●  Odoo: กำลังตรวจสอบ...")
        self.lbl_odoo_status.setStyleSheet("color:#FFB300; font-size:11px;")
        bc_outer.addWidget(self.lbl_odoo_status)

        self.lbl_bridge_status = QLabel("●  Bridge: กำลังเริ่ม...")
        self.lbl_bridge_status.setStyleSheet("color:#FFB300; font-size:11px;")
        bc_outer.addWidget(self.lbl_bridge_status)

        root.addWidget(bc_box)

        self.lbl_status = QLabel("กำลังโหลด model และกล้อง...")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        root.addWidget(self.lbl_status)

    def _open_crop_settings(self):
        if not self._camera_worker:
            return
        cur_rect = self._camera_worker._crop_rect
        cur_conf = self._camera_worker.conf
        inv_cfg = _load_invoice_config()
        cur_printer = inv_cfg['printer_name']
        cur_auto_print = inv_cfg['auto_print_enabled']
        cur_auto_create = inv_cfg['auto_create_enabled']
        dlg = CropSettingsDialog(cur_rect, cur_conf, cur_printer, cur_auto_print, cur_auto_create, parent=self)
        self._camera_worker.set_emit_raw(True)
        self._camera_worker.raw_frame_ready.connect(dlg.update_frame)
        try:
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_rect = dlg.get_rect()
                new_conf = dlg.get_conf()
                new_printer = dlg.get_printer()
                new_auto_print = dlg.get_auto_print_enabled()
                new_auto_create = dlg.get_auto_create_enabled()
                self._camera_worker.set_crop_rect(new_rect)
                self._camera_worker.set_conf(new_conf)
                try:
                    _save_settings(new_rect, new_conf)
                    _save_invoice_printer(new_printer)
                    _save_invoice_auto_print(new_auto_print)
                    _save_invoice_auto_create(new_auto_create)
                    self.lbl_status.setText(
                        f"บันทึก: crop {new_rect[2]*100:.0f}%×{new_rect[3]*100:.0f}%, conf {new_conf:.2f}"
                    )
                except Exception as e:
                    self.lbl_status.setText(f"บันทึก settings ล้มเหลว: {e}")
        finally:
            try:
                self._camera_worker.raw_frame_ready.disconnect(dlg.update_frame)
            except Exception:
                pass
            self._camera_worker.set_emit_raw(False)

    def _preconnect_odoo(self):
        try:
            OdooConn.ensure()
        except Exception:
            pass

    def _start_camera(self):
        self._camera_worker = CameraWorker(DEFAULT_MODEL)
        self._camera_worker.frame_ready.connect(self._on_frame)
        self._camera_worker.status_message.connect(self.lbl_status.setText)
        self._camera_worker.model_ready.connect(self._on_model_ready)
        self._camera_worker.camera_error.connect(self._on_camera_error)
        self._camera_worker.image_infer_done.connect(self._counter_panel._on_image_result)
        self._camera_worker.image_infer_error.connect(self._counter_panel._on_infer_error)
        self._counter_panel.image_infer_requested.connect(self._camera_worker.infer_image)
        self._counter_panel.snapshot_requested.connect(self._on_snapshot_requested)
        self._camera_worker.start()

    def _on_snapshot_requested(self, picking_name: str):
        if not self._camera_worker:
            return
        safe = "".join(c if c.isalnum() or c in '-_' else '_' for c in picking_name)
        filename = f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_{safe}.png"
        self._camera_worker.save_snapshot(_get_base_dir() / 'snapshots', filename)

    def _on_model_ready(self, name: str):
        color = "#FF9800" if "openvino" in name.lower() else "#4CAF50"
        self.lbl_status.setText(f"Model: {name}  ●  กล้องพร้อม — รอสแกน Barcode")
        self.lbl_status.setStyleSheet(f"color:{color}; font-size:12px; font-weight:bold;")

    def _on_camera_error(self, msg: str):
        self.lbl_status.setStyleSheet("color:#EF5350; font-size:12px; font-weight:bold;")
        self.lbl_status.setText(f"⚠ กล้องไม่พร้อม — {msg}")

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
        w.origin_ready.connect(self._bridge.broadcast)
        w.invoice_job_ready.connect(self._on_invoice_job_ready)
        w.finished.connect(lambda: self._workers.discard(w))
        self._workers.add(w)
        w.start()

    def _on_invoice_job_ready(self, sale_order_id: int, picking_name: str):
        if not _load_invoice_config()['auto_print_enabled']:
            return
        self._invoice_queue.append((sale_order_id, picking_name))
        self._pump_invoice_queue()

    def _pump_invoice_queue(self):
        if self._invoice_worker is not None or not self._invoice_queue:
            return
        sale_order_id, picking_name = self._invoice_queue.popleft()
        w = InvoicePrintWorker(sale_order_id, picking_name)
        w.print_status.connect(self._on_invoice_print_status)
        w.finished.connect(self._on_invoice_worker_finished)
        self._invoice_worker = w
        w.start()

    def _on_invoice_worker_finished(self):
        self._invoice_worker = None
        self._pump_invoice_queue()

    def _on_invoice_print_status(self, level: str, message: str):
        color = {'ok': '#4CAF50', 'checking': '#888', 'warn': '#EF9A9A'}.get(level, '#888')
        self.lbl_status.setStyleSheet(f"color:{color}; font-size:12px;")
        self.lbl_status.setText(message)

    def _on_counter_closed(self):
        if self._camera_worker:
            self._camera_worker.set_inference_enabled(False)
        self._barcode_listener.set_active(True)
        self.lbl_bc_icon.setText("⬜")
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        self.lbl_status.setText("ปิดหน้าต่างนับแล้ว — พร้อมสแกนใบใหม่")

    def _on_barcode_data(self, entry: dict):
        self.lbl_bc_icon.setText("✅")
        self.lbl_status.setStyleSheet("color:#4CAF50; font-size:12px; font-weight:bold;")
        self.lbl_status.setText(f"พบ {entry['picking']['name']} — เปิดหน้าต่างนับ")
        self._barcode_listener.set_active(False)
        if self._camera_worker:
            self._camera_worker.set_inference_enabled(True)
        self._counter_panel.popup(entry)

    def _on_not_found(self, msg: str):
        self.lbl_bc_icon.setText("❌")
        self.lbl_status.setStyleSheet("color:#EF9A9A; font-size:12px;")
        self.lbl_status.setText(msg)

    def _on_error(self, msg: str):
        self.lbl_bc_icon.setText("❌")
        self.lbl_status.setStyleSheet("color:#EF9A9A; font-size:12px;")
        self.lbl_status.setText(f"Error: {msg}")
        self._odoo_status_worker.check_now()

    def _on_odoo_status(self, state: str, msg: str):
        color = {'ok': '#4CAF50', 'fail': '#EF5350', 'checking': '#FFB300'}.get(state, '#888')
        self.lbl_odoo_status.setText(f"●  Odoo: {msg}")
        self.lbl_odoo_status.setStyleSheet(f"color:{color}; font-size:11px;")

    def _on_bridge_status(self, state: str, msg: str):
        color = {'ok': '#4CAF50', 'fail': '#EF5350', 'starting': '#FFB300'}.get(state, '#888')
        self.lbl_bridge_status.setText(f"●  Bridge: {msg}")
        self.lbl_bridge_status.setStyleSheet(f"color:{color}; font-size:11px;")

    def closeEvent(self, event):
        self._barcode_listener.stop_listener()
        self._barcode_listener.wait()
        self._odoo_status_worker.stop()
        self._odoo_status_worker.wait()
        self._bridge.stop()
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
