"""จำลอง popup นับซอง กรณีสินค้าเดียวกันมีหลาย lot (ไม่ต่อกล้อง/Odoo จริง)

เปิด CounterPanel ตัวจริงด้วย entry ปลอม (mock ของ payload ที่ BarcodeWorker.data_ready
ส่งออกมาปกติ — รวม field 'qty' ต่อ lot ที่ดึงจาก stock.move.line.quantity จริง) เพื่อดู
layout การ์ดสินค้าเวลามีหลาย lot จริง ๆ:
  - สินค้า A: 2 lot รหัสยาว ต้องตัดเหลือ 4 ตัว (ตำแหน่ง 10-13)  -> "Lot: 0266: 30 ซอง (EXP ...)"
  - สินค้า B: 1 lot รหัสยาว + 1 lot สั้นกว่า 13 ตัว (fallback)  -> โชว์เต็มไม่ตัด
  - สินค้า C: ไม่มี lot เลย                                    -> "Lot: -"

ปลอดภัย: ปิด popup แล้วจะไม่ยิงไป Odoo จริง เพราะ CounterPanel.hideEvent() เรียก
_save_to_odoo() ซึ่ง no-op ทันทีถ้า _pending_product_counts ยังเป็น None (ค่านี้จะถูก
set ก็ต่อเมื่อมีการนับจากกล้องจริงจนครบเป๊ะเท่านั้น — สคริปต์นี้ไม่มีกล้องเลยจึงไม่มีทาง
เข้าเงื่อนไขนั้น)

รัน: python test\\demo_multi_lot_popup.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication

from odoo_counter_app import CounterPanel

MOCK_ENTRY = {
    'picking': {
        'id': 999999,
        'name': 'MOCK/OUT/00001',
        'partner_id': (1, 'ลูกค้าจำลอง (demo)'),
        'state': 'assigned',
    },
    'moves': [
        {'product_id': (101, '[3G-A] Houjicha Rich 95% 3.1g (1 sachet)'), 'product_uom_qty': 50},
        {'product_id': (102, '[3G-B] Genmaicha Powder 3 g'),             'product_uom_qty': 30},
        {'product_id': (103, '[3G-C] Classic Blend 3g'),                 'product_uom_qty': 20},
    ],
    'lots_by_product': {
        101: [
            {'name': 'HR0008HKW026621326R', 'expiration_date': '2026-09-01 00:00:00', 'qty': 30.0},
            {'name': 'HR0008HKW099921326R', 'expiration_date': '2026-11-15 00:00:00', 'qty': 20.0},
        ],
        102: [
            {'name': 'GM0002XYZ011122333R', 'expiration_date': '2026-10-01 00:00:00', 'qty': 30.0},
            {'name': 'LOT9', 'expiration_date': '', 'qty': 5.0},
        ],
        # 103: ไม่มี key -> การ์ดจะโชว์ "Lot: -"
    },
}


def main() -> None:
    app = QApplication(sys.argv)
    panel = CounterPanel()
    panel.closed.connect(app.quit)
    panel.popup(MOCK_ENTRY)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
