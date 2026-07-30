"""ทดสอบ Launcher._install() แบบ offline (ไม่แตะ GitHub/เน็ต)

เคสที่ต้องผ่าน:
  1. อัปเดตปกติ           -> app/ ถูกแทนที่ครบ, ไม่มี app/app/ ซ้อน, version.txt = ตัวใหม่
  2. โฟลเดอร์เดิมถูกล็อก   -> ยกเลิกการอัปเดต, ของเดิมยังครบ, version.txt ยังเป็นตัวเก่า

เคส 2 คือบั๊กที่ทำให้เครื่อง user พัง: rmtree(ignore_errors=True) ลบไปได้ครึ่งทางแล้วเงียบ
shutil.move เลยไปซ้อนเป็น app/app/ และ launcher เรียก exe เก่าที่ _internal แหว่ง

รัน: python test\test_launcher_install.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_launcher():
    spec = importlib.util.spec_from_file_location('launcher_under_test',
                                                  PROJECT_ROOT / 'launcher.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def point_launcher_at(mod, base: Path):
    """launcher คำนวณ path ทั้งหมดตอน import — ชี้ใหม่ให้ไปเล่นในโฟลเดอร์ชั่วคราวแทน"""
    mod.BASE = base
    mod.APP_DIR = base / mod.APP_DIR_NAME
    mod.APP_EXE = mod.APP_DIR / mod.APP_EXE_NAME
    mod.VERSION_FILE = mod.APP_DIR / 'version.txt'
    mod.TMP_DIR = base / 'update_tmp'
    mod.LOG_FILE = base / 'launcher.log'


def make_old_app(app_dir: Path, version: str):
    (app_dir / '_internal' / 'setuptools' / '_vendor').mkdir(parents=True, exist_ok=True)
    (app_dir / 'odoo_counter.exe').write_text('OLD EXE', encoding='utf-8')
    (app_dir / '_internal' / 'setuptools' / '_vendor' / 'Lorem ipsum.txt').write_text(
        'old data', encoding='utf-8')
    (app_dir / 'version.txt').write_text(version, encoding='utf-8')


def make_zip(zip_path: Path):
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('app/odoo_counter.exe', 'NEW EXE')
        zf.writestr('app/_internal/setuptools/_vendor/Lorem ipsum.txt', 'new data')
        zf.writestr('app/version.txt', '0.0.0')


def check(label: str, ok: bool, detail: str = ''):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ''))
    return ok


def test_normal_update(mod) -> bool:
    print('เคส 1: อัปเดตปกติ')
    base = Path(tempfile.mkdtemp(prefix='launcher_ok_'))
    point_launcher_at(mod, base)
    mod.APP_DIR.mkdir()
    make_old_app(mod.APP_DIR, '1.6')
    zip_path = base / 'update.zip'
    make_zip(zip_path)

    mod.Launcher._install(None, zip_path, 'v1.7')

    ok = True
    ok &= check('ไม่มี app/app/ ซ้อน', not (mod.APP_DIR / 'app').exists())
    ok &= check('exe เป็นตัวใหม่', mod.APP_EXE.read_text(encoding='utf-8') == 'NEW EXE')
    ok &= check('ไฟล์ลึกใน _internal มาครบ',
                (mod.APP_DIR / '_internal' / 'setuptools' / '_vendor' / 'Lorem ipsum.txt')
                .read_text(encoding='utf-8') == 'new data')
    ok &= check('version.txt = 1.7', mod.VERSION_FILE.read_text(encoding='utf-8') == '1.7')
    ok &= check('เก็บกวาด update_tmp แล้ว', not mod.TMP_DIR.exists())
    ok &= check('ไม่มีเศษ app_old_* ค้าง', not list(base.glob('app_old_*')))
    shutil.rmtree(base, ignore_errors=True)
    return bool(ok)


def test_locked_app_dir(mod) -> bool:
    print('เคส 2: โฟลเดอร์เดิมถูกล็อก (จำลองว่าแอปยังเปิดอยู่)')
    base = Path(tempfile.mkdtemp(prefix='launcher_locked_'))
    point_launcher_at(mod, base)
    mod.APP_DIR.mkdir()
    make_old_app(mod.APP_DIR, '1.6')
    zip_path = base / 'update.zip'
    make_zip(zip_path)

    # Windows ห้าม rename โฟลเดอร์ที่เป็น cwd ของ process ที่รันอยู่ = ล็อกเหมือนแอปเปิดค้าง
    cwd = os.getcwd()
    os.chdir(mod.APP_DIR)
    try:
        raised = None
        try:
            mod.Launcher._install(None, zip_path, 'v1.7')
        except Exception as e:
            raised = e
    finally:
        os.chdir(cwd)

    ok = True
    ok &= check('โยน error ออกมา (ไม่เงียบ)', raised is not None, str(raised))
    ok &= check('ไม่มี app/app/ ซ้อน', not (mod.APP_DIR / 'app').exists())
    ok &= check('exe เดิมยังอยู่ครบ',
                mod.APP_EXE.exists() and mod.APP_EXE.read_text(encoding='utf-8') == 'OLD EXE')
    ok &= check('ไฟล์ลึกของเดิมไม่โดนลบ',
                (mod.APP_DIR / '_internal' / 'setuptools' / '_vendor' / 'Lorem ipsum.txt').exists())
    ok &= check('version.txt ยังเป็น 1.6 (รอบหน้าจะลองใหม่)',
                mod.VERSION_FILE.read_text(encoding='utf-8') == '1.6')
    shutil.rmtree(base, ignore_errors=True)
    return bool(ok)


def main() -> int:
    mod = load_launcher()
    results = [test_normal_update(mod), test_locked_app_dir(mod)]
    print()
    if all(results):
        print('ผ่านทั้งหมด')
        return 0
    print('มีเคสที่ไม่ผ่าน')
    return 1


if __name__ == '__main__':
    sys.exit(main())
