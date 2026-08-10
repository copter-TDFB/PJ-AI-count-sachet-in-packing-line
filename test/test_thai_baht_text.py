"""ทดสอบฟังก์ชันแปลงจำนวนเงิน -> คำอ่านภาษาไทย (Thai baht-text) แบบ offline

ไม่แตะ Odoo/เน็ตเลย เคสจำนวนเต็มบาทเป็นค่าจริงที่ดึงมาจาก production
(account.move.x_studio_thai_bahttext ที่มีอยู่แล้ว เข้าโดย action เดิมด้วย account ที่มีสิทธิ์)
ตอนออกแบบฟีเจอร์นี้ — ดู
docs/superpowers/specs/2026-08-10-thai-baht-text-local-computation-design.md
เคสสตางค์/หลักล้านเป็นกฎมาตรฐานของ BAHTTEXT ที่ไม่มีตัวอย่างจริงให้เทียบ แต่ต้องถูกต้องตามหลักเกณฑ์

รัน: python test\\test_thai_baht_text.py
"""
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_app():
    spec = importlib.util.spec_from_file_location(
        'odoo_counter_app_under_test', PROJECT_ROOT / 'odoo_counter_app.py'
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ''))
    return ok


# (amount, expected_text)
CASES = [
    # ค่าจริงจาก production (มาจาก action เดิม ผ่าน account ที่มีสิทธิ์)
    (625, 'หกร้อยยี่สิบห้าบาทถ้วน'),
    (21465, 'สองหมื่นหนึ่งพันสี่ร้อยหกสิบห้าบาทถ้วน'),
    (10518, 'หนึ่งหมื่นห้าร้อยสิบแปดบาทถ้วน'),
    (7380, 'เจ็ดพันสามร้อยแปดสิบบาทถ้วน'),
    (608, 'หกร้อยแปดบาทถ้วน'),
    (505, 'ห้าร้อยห้าบาทถ้วน'),
    (500, 'ห้าร้อยบาทถ้วน'),
    # เคสกฎพิเศษของ BAHTTEXT ที่ไม่มีตัวอย่างจริงในข้อมูล production
    (0, 'ศูนย์บาทถ้วน'),
    (1, 'หนึ่งบาทถ้วน'),
    (11, 'สิบเอ็ดบาทถ้วน'),
    (21, 'ยี่สิบเอ็ดบาทถ้วน'),
    (3690.50, 'สามพันหกร้อยเก้าสิบบาทห้าสิบสตางค์'),
    (0.01, 'ศูนย์บาทหนึ่งสตางค์'),
    (1_000_000, 'หนึ่งล้านบาทถ้วน'),
    (11_000_000, 'สิบเอ็ดล้านบาทถ้วน'),
]


def test_amount_to_thai_baht_text(mod) -> bool:
    print('แปลงจำนวนเงิน -> คำอ่านภาษาไทย')
    ok = True
    for amount, expected in CASES:
        actual = mod._amount_to_thai_baht_text(amount)
        ok &= check(f'{amount} -> {expected!r}', actual == expected, f'ได้ {actual!r}')
    return bool(ok)


def main() -> int:
    mod = load_app()
    results = [test_amount_to_thai_baht_text(mod)]
    print()
    if all(results):
        print('ผ่านทั้งหมด')
        return 0
    print('มีเคสที่ไม่ผ่าน')
    return 1


if __name__ == '__main__':
    sys.exit(main())
