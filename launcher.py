"""
Odoo Pack Counter — Auto-updating launcher.

Layout เมื่อ build เป็น .exe:
  AppFolder/
    ├── launcher.exe
    └── app/
         ├── odoo_counter.exe
         ├── ai_3g_v12.pt
         ├── ถูก.mp3 / ผิด.mp3
         └── version.txt

flow: launcher → check GitHub Releases → ถ้ามี version ใหม่ download + replace app/
       → launch app/odoo_counter.exe
"""
import shutil
import ssl
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from tkinter import ttk


def _make_ssl_context() -> ssl.SSLContext:
    # PyInstaller .exe ที่ run บนเครื่องอื่นมักไม่มี CA store ของระบบให้ verify GitHub
    # ลำดับความน่าเชื่อถือ: truststore (อ่าน Windows cert store, รองรับ corporate proxy) →
    # certifi (CA bundle ที่ bundle มากับ exe) → default
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    return ssl.create_default_context()


_SSL_CTX = _make_ssl_context()

# ── Config — เปลี่ยนเป็น repo จริงของคุณ ──────────────────────
GITHUB_REPO = "copter-TDFB/PJ-AI-count-sachet-in-packing-line"
APP_DIR_NAME = "app"
APP_EXE_NAME = "odoo_counter.exe"
ASSET_SUFFIX = ".zip"

# ── Paths ────────────────────────────────────────────────────
def _base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

BASE         = _base_dir()
APP_DIR      = BASE / APP_DIR_NAME
APP_EXE      = APP_DIR / APP_EXE_NAME
VERSION_FILE = APP_DIR / "version.txt"
TMP_DIR      = BASE / "update_tmp"
LOG_FILE     = BASE / "launcher.log"


def log(msg: str):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass


def parse_version(v: str) -> tuple:
    try:
        # ﻿ = UTF-8 BOM ที่บางครั้งติดมากับ version.txt (ไม่ถูกตัดด้วย .strip())
        return tuple(int(p) for p in v.lstrip('﻿').strip().lstrip('v').split('.'))
    except Exception:
        return (0, 0, 0)


def get_local_version() -> str:
    if VERSION_FILE.exists():
        try:
            return VERSION_FILE.read_text(encoding='utf-8-sig').strip()
        except Exception:
            pass
    return "0.0.0"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_latest_release() -> dict:
    # api.github.com จำกัด unauthenticated request ไว้ 60 ครั้ง/ชม. ต่อ IP รวมทั้งวงเน็ต —
    # เครื่อง user ที่แชร์ IP กับเครื่องอื่นในโรงงานโดน 403 rate limit exceeded กันทั้งวง
    # ใช้ redirect ของหน้าเว็บ releases/latest แทน (คนละ endpoint ไม่โดนโควตาเดียวกัน)
    url = f"https://github.com/{GITHUB_REPO}/releases/latest"
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=_SSL_CTX))
    req = urllib.request.Request(url, method='HEAD')
    location = ''
    try:
        opener.open(req, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            location = e.headers.get('Location', '')
    if not location:
        raise RuntimeError(f"no release found for {GITHUB_REPO}")

    tag = location.rstrip('/').rsplit('/', 1)[-1]
    version = tag.lstrip('v')
    asset_name = f"odoo-counter-{version}{ASSET_SUFFIX}"
    download_url = f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/{asset_name}"

    size = 0
    try:
        head_req = urllib.request.Request(download_url, method='HEAD')
        with urllib.request.urlopen(head_req, timeout=10, context=_SSL_CTX) as r:
            size = int(r.headers.get('Content-Length', 0))
    except Exception:
        pass  # progress bar จะไม่ขึ้น % แต่ดาวน์โหลดยังทำงานได้ปกติ

    return {
        'tag_name': tag,
        'assets': [{'name': asset_name, 'browser_download_url': download_url, 'size': size}],
    }


class Launcher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Odoo Pack Counter")
        self.root.geometry("440x170")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e2e")

        tk.Label(self.root, text="Odoo Pack Counter",
                 font=("Segoe UI", 14, "bold"),
                 fg="#90CAF9", bg="#1e1e2e").pack(pady=(22, 4))

        self.lbl_version = tk.Label(self.root, text=f"installed: {get_local_version()}",
                                    font=("Segoe UI", 9),
                                    fg="#666", bg="#1e1e2e")
        self.lbl_version.pack()

        self.status = tk.StringVar(value="กำลังตรวจสอบเวอร์ชัน...")
        tk.Label(self.root, textvariable=self.status,
                 font=("Segoe UI", 10),
                 fg="#bbb", bg="#1e1e2e").pack(pady=(10, 4))

        self.progress = ttk.Progressbar(self.root, length=380, mode='determinate')
        self.progress.pack(pady=8)

        self.root.after(150, lambda: threading.Thread(target=self._run, daemon=True).start())

    def set_status(self, text: str):
        self.root.after(0, self.status.set, text)

    def set_progress(self, percent: float):
        self.root.after(0, lambda: self.progress.configure(value=percent))

    def _run(self):
        try:
            self._check_and_update()
        except Exception as e:
            log(f"UPDATE ERROR: {e}\n{traceback.format_exc()}")
            self.set_status(f"ข้ามการอัปเดต: {e}")
        self.root.after(400, self._launch_app)

    def _check_and_update(self):
        local = get_local_version()
        log(f"local={local}")
        try:
            release = fetch_latest_release()
        except Exception as e:
            self.set_status("ออฟไลน์ — ใช้เวอร์ชันที่ติดตั้งไว้")
            log(f"fetch failed: {e}")
            return

        remote = release.get('tag_name', '0.0.0')
        log(f"remote={remote}")
        if parse_version(remote) <= parse_version(local):
            self.set_status(f"เวอร์ชันล่าสุดแล้ว ({local})")
            return

        asset = next((a for a in release.get('assets', [])
                      if a['name'].lower().endswith(ASSET_SUFFIX)), None)
        if not asset:
            self.set_status("ไม่พบไฟล์ zip ใน release")
            return

        self.set_status(f"พบเวอร์ชันใหม่ {remote} — กำลังดาวน์โหลด...")
        zip_path = self._download(asset['browser_download_url'], asset.get('size', 0))
        self.set_status("กำลังติดตั้ง...")
        self._install(zip_path, remote)
        self.set_status(f"ติดตั้ง {remote} สำเร็จ")
        self.root.after(0, lambda: self.lbl_version.configure(text=f"installed: {remote.lstrip('v')}"))

    def _download(self, url: str, total: int) -> Path:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = TMP_DIR / "update.zip"
        with urllib.request.urlopen(url, timeout=60, context=_SSL_CTX) as r, open(zip_path, 'wb') as f:
            downloaded = 0
            while True:
                buf = r.read(65536)
                if not buf:
                    break
                f.write(buf)
                downloaded += len(buf)
                if total > 0:
                    self.set_progress(downloaded / total * 100)
        self.set_progress(100)
        return zip_path

    def _install(self, zip_path: Path, version: str):
        extract_dir = TMP_DIR / "extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        # zip อาจมี root เป็น "app/" หรือ contents ตรง ๆ — รองรับทั้งคู่
        new_app = extract_dir / "app" if (extract_dir / "app").is_dir() else extract_dir

        if APP_DIR.exists():
            shutil.rmtree(APP_DIR, ignore_errors=True)
        shutil.move(str(new_app), str(APP_DIR))
        (APP_DIR / "version.txt").write_text(version.lstrip('v'), encoding='utf-8')
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    def _launch_app(self):
        if not APP_EXE.exists():
            self.set_status(f"ไม่พบ {APP_EXE_NAME}")
            self.root.after(3000, self.root.destroy)
            return
        try:
            subprocess.Popen([str(APP_EXE)], cwd=str(APP_DIR))
        except Exception as e:
            log(f"launch failed: {e}")
            self.set_status(f"เปิดแอปไม่ได้: {e}")
            self.root.after(3000, self.root.destroy)
            return
        self.root.after(400, self.root.destroy)

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    Launcher().run()
