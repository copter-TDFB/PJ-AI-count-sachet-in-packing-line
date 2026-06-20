# Project Context - PJ AI Count Sachet PK

อัปเดตล่าสุด: 2026-06-16

ไฟล์นี้เป็นเอกสาร onboarding สำหรับคนหรือ AI ที่กลับมาแก้โปรเจกต์นี้ในรอบถัดไป ให้อ่านไฟล์นี้ก่อนเปิดโค้ด เพื่อเข้าใจภาพรวม, logic, จุดเสี่ยง และวิธี build/release โดยไม่ต้องไล่ทั้งโปรเจกต์ตั้งแต่ต้น

## TL;DR

โปรเจกต์นี้เป็น Windows desktop app สำหรับไลน์ packing ใช้กล้อง + YOLO OBB นับซองสินค้า 3g ตามใบ Pack ใน Odoo

Flow ใช้งานจริง:

1. เปิด `launcher.exe`
2. launcher เช็ก GitHub Release ล่าสุด ถ้ามี version ใหม่จะ download zip แล้ว replace โฟลเดอร์ `app/`
3. launcher เปิด `app/odoo_counter.exe`
4. user สแกน barcode ของใบ pack
5. app ค้นหา `stock.picking` ใน Odoo จาก `x_studio_tracking_no`
6. app ดึง move lines เฉพาะสินค้า 3g ที่รองรับ + lot/expiration จาก `stock.move.line` / `stock.lot`
7. popup หน้าต่างกล้องขึ้นมาและเปิด AI inference (inference จะปิดไว้จนกว่า popup จะเปิด เพื่อประหยัด CPU)
8. AI ตรวจจับ OBB, นับจำนวนตาม class, เทียบกับ demand ใน Odoo
9. ถ้าตรงทั้งหมด app เล่นเสียงถูก, snapshot ภาพไป `snapshots/`, แสดง toast แล้ว auto-hide popup; post note กลับ Odoo เงียบ ๆ ตอน popup hide
10. ถ้าขาด/เกิน/เจอสินค้านอก order app เล่นเสียงผิด, ขึ้น alert กลางจอ และเขย่าหน้าต่างแบบ MSN nudge

## Current Important State

- แอปหลัก: `odoo_counter_app.py`
- launcher auto-update: `launcher.py`
- batch evaluation tool: `batch_eval_app.py`
- โมเดลหลักปัจจุบัน: `ai_3g_v12.pt`
- OpenVINO model หลักปัจจุบัน: `ai_3g_v12_openvino_model/`
- default confidence ใน source: `DEFAULT_CONF = 0.7`
- ค่าที่อยู่ใน `dist_release/app/version.txt` ปัจจุบัน: `1.2`
- GitHub Release ล่าสุดบน remote: `v1.1.4` (2026-05-18)
- GitHub repo ที่ launcher เช็ก release: `copter-TDFB/PJ-AI-count-sachet-in-packing-line`
- Odoo target ปัจจุบัน: production (`https://tdfb.odoo.com`, db `tdfb`) — เคยมี state ชี้ test instance ตอน dev แต่ถูกย้ายกลับ prod แล้ว

## Directory And File Map

ไฟล์ source หลัก:

- `odoo_counter_app.py` - แอปหลัก PyQt6 สำหรับ scan barcode, ต่อ Odoo, เปิดกล้อง, run YOLO, นับซอง, post note กลับ Odoo
- `launcher.py` - tkinter launcher ที่เช็ก GitHub Releases, download update, install `app/`, แล้วเปิด exe หลัก
- `batch_eval_app.py` - PyQt6 tool สำหรับประเมินโมเดลกับ dataset folder และ export CSV
- `build.ps1` - build exe และประกอบ release folder
- `release.ps1` - build, zip, upload GitHub Release ผ่าน `gh`
- `combined-auto-print.user.js` - Tampermonkey userscript auto-print ใบปะหน้า (Shopee/TikTok/Odoo/Lazada); รับ order ผ่าน WebSocket bridge port 9999, paste, หรือ scanner; auto-update จาก `main`
- `AGENTS.md` - คำสั่งสำหรับ AI ให้อ่าน `PROJECT_CONTEXT.md` ก่อนทำงาน
- `CLAUDE.md` - guidance สำหรับ Claude Code (สรุปสั้น ชี้มาที่เอกสารนี้)
- `PROJECT_CONTEXT.md` - เอกสารนี้

โมเดลและ asset:

- `ai_3g_v12.pt` - PyTorch model ที่ code/build ใช้ปัจจุบัน
- `ai_3g_v12_openvino_model/` - OpenVINO export ที่ใช้ก่อน `.pt` เพื่อให้ startup เร็วและลดปัญหา export ใน exe
- `ai_3g_v9.pt`, `ai_3g_v10.pt`, `ai_3g_v11.pt` - โมเดลรุ่นเก่าที่ยังเก็บไว้ใน root (untracked, ไม่ถูก bundle)
- `ai_3g_v4`, `v5`, `v7`, `v9`, `v10`, `v11` `_openvino_model/` - export ของโมเดลรุ่นเก่า (เก็บไว้เผื่อเทียบ)
- `ถูก.mp3` - เสียงเมื่อ count ตรง
- `ผิด.mp3` - เสียงเมื่อ count ผิด
- `crop_config.json` - per-machine config ของ crop rect และ confidence (gitignored)
- `snapshots/` - โฟลเดอร์ที่ app สร้างอัตโนมัติเมื่อนับครบ; เก็บภาพ raw จากกล้องตอน trigger save พร้อม timestamp + picking name

Generated/build outputs:

- `build/` - PyInstaller build temp
- `dist/` - PyInstaller dist
- `dist_release/` - release folder ที่เอาไปทดสอบหรือ zip
- `odoo-counter-*.zip` - release package ที่ upload GitHub Release
- `*_openvino_model/` - exported OpenVINO model directory
- `__pycache__/`
- `*.spec` - PyInstaller spec generated จาก build

## Runtime Layout

หลังรัน `.\build.ps1 <version>` จะได้ layout:

```text
dist_release/
  launcher.exe
  app/
    odoo_counter.exe
    ai_3g_v12.pt
    ai_3g_v12_openvino_model/
    version.txt
    ถูก.mp3
    ผิด.mp3
    _internal/
```

จุดสำคัญ:

- user ควรเปิด `launcher.exe` ไม่ใช่ `app/odoo_counter.exe`
- launcher เป็นตัวคุม update ทั้งโฟลเดอร์ `app/`
- zip release ต้องมี root folder ชื่อ `app/` เพราะ launcher รองรับ payload แบบ `app/` และ `release.ps1` zip ด้วย `tar -caf <zip> -C dist_release app`
- `snapshots/` จะถูกสร้างข้าง `odoo_counter.exe` ตอน runtime ครั้งแรกที่นับครบ

## How To Run

รันแอปหลักตอน dev:

```powershell
python odoo_counter_app.py
```

รัน batch evaluator:

```powershell
python batch_eval_app.py
```

ทดสอบ build:

```powershell
.\build.ps1 1.2
.\dist_release\launcher.exe
```

Release:

```powershell
gh auth login
.\release.ps1 1.2.0 "release notes"
```

หมายเหตุ:

- `launcher.py` ใน source mode คาดว่า `app/` อยู่ข้าง launcher จึงเหมาะกับการทดสอบจาก `dist_release/` มากกว่ารันตรงจาก root
- ถ้ารัน `odoo_counter_app.py` ตรง ต้องมี dependency และ model อยู่ใน root project

## Dependencies

Python packages ที่ source import:

- `PyQt6`
- `opencv-python` หรือ package ที่ import เป็น `cv2`
- `numpy`
- `ultralytics`
- `openvino`
- `pynput`
- `websockets` (bridge ส่ง barcode ไป Tampermonkey ใน browser)
- `PyInstaller`
- `truststore`
- `certifi`

Tools สำหรับ build/release:

- Python บน Windows
- `tar` หรือ bsdtar ที่มากับ Windows 10+
- GitHub CLI `gh` และต้อง auth แล้ว

## Launcher Logic (`launcher.py`)

หน้าที่:

- แสดงหน้าต่างเล็กด้วย tkinter
- เช็ก version local จาก `app/version.txt`
- เรียก GitHub Releases API เพื่อดู release ล่าสุด
- ถ้า remote version ใหม่กว่า local จะ download `.zip`
- unzip แล้ว replace โฟลเดอร์ `app/`
- เปิด `app/odoo_counter.exe`

ค่าคงที่:

- `GITHUB_REPO = "copter-TDFB/PJ-AI-count-sachet-in-packing-line"`
- `APP_DIR_NAME = "app"`
- `APP_EXE_NAME = "odoo_counter.exe"`
- `ASSET_SUFFIX = ".zip"`
- `VERSION_FILE = BASE / "app/version.txt"`
- `TMP_DIR = BASE / "update_tmp"`
- `LOG_FILE = BASE / "launcher.log"`

Path logic:

- `_base_dir()` ใช้ `Path(sys.executable).parent` ถ้า frozen เป็น exe
- ถ้า run เป็น source จะใช้ `Path(__file__).parent`

SSL logic (`_make_ssl_context()`):

- ลองใช้ `truststore` ก่อน เพื่ออ่าน Windows certificate store (รองรับ corporate proxy/MITM cert)
- ถ้าไม่ได้ ใช้ `certifi` (CA bundle ที่ bundle มากับ exe)
- ถ้ายังไม่ได้ ใช้ `ssl.create_default_context()`
- context ถูกสร้างครั้งเดียวเป็น `_SSL_CTX` และส่งเข้า `urllib.request.urlopen(..., context=_SSL_CTX)`
- เหตุผลคือ exe ที่ build บนเครื่อง dev แล้วเอาไปรันบนเครื่อง user มักไม่มี CA store ของระบบ → เจอ `CERTIFICATE_VERIFY_FAILED` ตอน fetch GitHub

Version logic:

- `get_local_version()` อ่าน `app/version.txt` ด้วย `utf-8-sig` เพื่อรองรับ BOM
- `parse_version()` strip BOM (`﻿`), strip whitespace, strip `v`, แล้ว split ด้วย `.`
- ถ้า parse fail จะ fallback เป็น `(0, 0, 0)`
- remote version มาจาก `release["tag_name"]`
- update เมื่อ `parse_version(remote) > parse_version(local)`

Download/install logic:

- หา asset แรกที่ชื่อจบด้วย `.zip`
- download เป็น `update_tmp/update.zip`
- progress bar คำนวณจาก asset size ถ้ามี
- extract ไป `update_tmp/extracted`
- ถ้าใน zip มี root `app/` จะใช้ folder นั้น
- ถ้าไม่มี `app/` จะถือว่า content ใน zip คือ app payload โดยตรง
- ก่อน replace จะย้าย app เก่าไป `app_backup`
- หลังย้าย app ใหม่ จะเขียน `app/version.txt` เป็น remote version แบบไม่มี `v`
- ลบ `update_tmp`

Failure behavior:

- ถ้า fetch GitHub release fail จะ set status offline แล้วใช้ local app ต่อ
- ถ้า update fail จะ log ลง `launcher.log` แล้วพยายามเปิด local app ต่อ
- ถ้าไม่พบ `app/odoo_counter.exe` จะแสดง error แล้วปิด

## Main App Overview (`odoo_counter_app.py`)

แอปหลักเป็น PyQt6 แบ่งเป็น worker threads + UI:

- `MainWindow` เป็นหน้าหลักสแกน barcode
- `CounterPanel` เป็น popup นับซอง
- `CameraWorker` โหลดโมเดล warmup เปิดกล้อง และ run inference
- `BarcodeWorker` query Odoo จาก barcode (รวม lot/exp lookup)
- `OdooSaveWorker` post note กลับ Odoo
- `OdooStatusWorker` ping Odoo เป็นระยะ
- `GlobalBarcodeListener` รับ barcode global keyboard (VK-based, bypass IME)
- `CropSettingsDialog` ตั้งค่า crop/conf

ค่าคงที่สำคัญ:

- `ODOO_URL = 'https://tdfb.odoo.com'`
- `ODOO_DB = 'tdfb'`
- `ODOO_USER` และ `ODOO_PASSWORD` ถูก hard-code ใน source แต่ไม่ควร copy secret เพิ่มในเอกสารหรือ commit public
- `DEFAULT_MODEL = <base_dir>/ai_3g_v12.pt`
- `DEFAULT_CONF = 0.7`

Base path logic:

- `_get_base_dir()` คืน path ของ exe ถ้า frozen
- ถ้า run เป็น source คืน directory ของ `odoo_counter_app.py`
- model, mp3, crop config, snapshots อ้างอิงจาก base dir นี้ทั้งหมด

## Config Logic: Crop And Confidence

ไฟล์ config:

```text
crop_config.json
```

schema:

```json
{
  "x": 0.0,
  "y": 0.0,
  "w": 1.0,
  "h": 1.0,
  "conf": 0.7
}
```

ความหมาย:

- `x`, `y`, `w`, `h` เป็น normalized ratio 0..1 ของภาพหลัง camera preprocess
- `conf` เป็น confidence threshold สำหรับ YOLO

Precedence:

1. ถ้ามี `crop_config.json` และอ่านได้ จะใช้ค่าจากไฟล์
2. ถ้าไม่มีไฟล์หรือ parse fail จะใช้ default จาก source
3. default conf ปัจจุบันคือ `0.7`

Clamp:

- crop `x/y` ถูก clamp 0..1
- crop `w/h` ขั้นต่ำ 0.05 และไม่ให้เกินขอบภาพ
- conf ถูก clamp 0.05..0.95

สำคัญ:

- ถ้า user เคยกด save setting แล้ว `crop_config.json` มี `conf` อยู่ ค่าในไฟล์จะ override `DEFAULT_CONF`
- ถ้าต้องการให้เครื่องที่เคยตั้งค่าแล้วกลับมา 0.7 ต้องแก้ไฟล์ `crop_config.json` หรือเปิดหน้า setting แล้วเลื่อนเป็น 0.70 และกด save

## Odoo Logic

### `OdooConn`

หน้าที่:

- cache `uid` และ `models` XML-RPC proxy เพื่อไม่ต้อง login ใหม่ทุก request
- `ensure()` authenticate ผ่าน `/xmlrpc/2/common`
- ถ้า login fail จะ raise `RuntimeError`
- `reset()` clear cache ตอน connection fail
- ตอน startup `MainWindow.__init__` จะ spawn daemon thread เรียก `OdooConn.ensure()` เพื่อ pre-warm connection ตั้งแต่เปิดแอป

### `BarcodeWorker`

ทำงานใน `QThread` เพื่อไม่ให้ UI ค้าง

Input:

- barcode string จาก scanner หรือ textbox

Step 1: หา picking

- model: `stock.picking`
- method: `search_read`
- domain:
  - `x_studio_tracking_no = barcode`
  - `picking_type_id.name ilike Pack`
  - `state = assigned`
- fields:
  - `name`
  - `x_studio_tracking_no`
  - `partner_id`
  - `state`
  - `origin` (source document ref — ส่งต่อไป Tampermonkey ผ่าน bridge)
- limit 1

ถ้าไม่เจอ:

- emit `not_found(barcode)`

Step 2: หา stock moves ที่รองรับ

- model: `stock.move`
- method: `search_read`
- domain:
  - `picking_id = picking["id"]`
  - `state not in ["done", "cancel"]`
  - product name ilike หนึ่งในสินค้ารองรับ
- fields:
  - `product_id`
  - `product_uom_qty`

สินค้าที่รองรับใน search domain:

- `Excellent Rich 95% 3.1g (1 sachet)`
- `Medium Rich 95% 3.1g (1 sachet)`
- `Classic Rich 95% 3.1g (1 sachet)`
- `Houjicha Rich 95% 3.1g (1 sachet)`
- `Genmaicha Powder 3 g`

ถ้าเจอ picking แต่ไม่เจอ move ที่รองรับ:

- query moves ทั้งหมดใน picking ที่ยังไม่ done/cancel
- ถ้ามี moves จะ emit not_found พร้อมชื่อสินค้าจริงในใบ เพื่อช่วย debug ว่าชื่อสินค้าไม่ตรง domain
- ถ้าไม่มี moves จะบอกว่าไม่มี moves ที่ยังไม่เสร็จ

Step 3: หา lot + expiration date (ใหม่)

- query `stock.move.line` ด้วย `[['move_id', 'in', move_ids]]` ดึง `product_id`, `lot_id`, `lot_name`
- รวบรวม `lot_id` ที่ unique แล้วอ่าน `name` + `expiration_date` ทีเดียวจาก `stock.lot` (Odoo 15+) หรือ fallback `stock.production.lot` (รุ่นเก่า)
- map เป็น dict `lots_by_product: { product_id: [{name, expiration_date}, ...] }` โดย dedupe ตาม name
- ถ้า move line ไม่มี `lot_id` แต่มี `lot_name` (case lot ที่ยังไม่ถูก register) จะใช้ `lot_name` แทน, exp = ''
- ถ้า lookup ทั้งบล็อค fail จะกลืน exception เงียบ ๆ — โหมดไม่มี lot ยังทำงานต่อได้

ถ้าสำเร็จ:

- emit `data_ready({"picking": picking, "moves": moves, "lots_by_product": lots_by_product})`

ถ้า error:

- reset OdooConn
- emit `error_occurred(str(e))`

### `OdooSaveWorker`

ทำงานหลัง popup hide เท่านั้น (ดู Auto-save flow ด้านล่าง)

Input:

- `picking_id`
- `product_counts` list ที่มี `product_name`, `counted`, `demand`

Logic:

- สร้าง body เช่น `AI นับ <product>: นับได้ <counted> / <demand> pcs`
- call `stock.picking.message_post`
- `message_type = comment`
- `subtype_xmlid = mail.mt_note`

Signal:

- success emit `save_done` (ปัจจุบัน `CounterPanel` ไม่ subscribe เพราะ toast แสดงไปแล้วก่อน save)
- error emit `save_error` — `CounterPanel` log ลง stdout เฉย ๆ ไม่ขึ้น toast (เพราะ UI ถูก hide ไปแล้ว)

### `OdooStatusWorker`

หน้าที่:

- ping Odoo ทุก 30 วินาที
- ใช้ `_PingTransport` (`xmlrpc.client.SafeTransport` ที่ override `make_connection` ให้ set `conn.timeout = 5`)
- เปิด `xmlrpc.client.ServerProxy(.../xmlrpc/2/common, transport=_PingTransport)` แล้วเรียก `proxy.version()`
- มี `check_now()` ที่ set `threading.Event` ปลุก loop ทันที (ใช้ตอน barcode worker เจอ error เพื่อ refresh status)
- emit `status_changed(state, message)`:
  - `checking` + `"กำลังตรวจสอบ..."`
  - `ok` + `"เชื่อมต่อแล้ว (<server_version>)"`
  - `fail` + `"เชื่อมต่อไม่ได้ — <err>"` (err ถูก truncate ที่ 70 chars)
- ตอน fail จะเรียก `OdooConn.reset()` ด้วย เพื่อบังคับ relogin ใน worker ถัดไป

ใน `MainWindow` เอา status ไปแสดงใน `lbl_odoo_status` ใต้ barcode input (สีเขียว/แดง/เหลือง)

## Barcode Input Logic

มี input 2 ทาง:

1. `QLineEdit` ในแอป เมื่อแอปมี focus
2. `GlobalBarcodeListener` ด้วย `pynput` เมื่อแอปไม่มี focus หรือถูกย่อ

`GlobalBarcodeListener`:

- เก็บ key chars ลง buffer
- ถ้าระยะห่างระหว่าง key > 0.15 วินาที จะ reset buffer เพราะถือว่าไม่ใช่ barcode scanner burst
- เมื่อกด Enter:
  - รวม buffer เป็น barcode
  - clear buffer
  - ถ้า length >= 4 emit `barcode_ready`
- Backspace ลบตัวท้ายจาก buffer
- ใช้ `_VK_MAP` map virtual-key code → ASCII โดยตรง:
  - A-Z (65-90), 0-9 (48-57), numpad 0-9 (96-105), `-` (189/109), `/` (191/111), `.` (190/110)
- VK-based mapping ตั้งใจให้ bypass IME ทุกภาษา (ก่อนหน้านี้ใช้ `key.char` ทำให้สแกนไม่ติดเวลา layout เป็นไทยหรือเมื่อ IME ไทยเปิดอยู่)

Focus logic:

- `MainWindow` connect `QApplication.focusChanged`
- ถ้าแอปมี focus จะ suppress global listener เพื่อให้ Qt input จัดการแทน
- ถ้าแอปไม่มี focus global listener จะรับ scan และ update text ใน barcode input

Counter popup logic:

- เมื่อเจอ picking แล้ว จะปิด barcode listener ชั่วคราว (`set_active(False)`) และ enable camera inference
- เมื่อปิด counter popup จะเปิด barcode listener กลับ (`set_active(True)`) และ disable camera inference

## Barcode Bridge Logic

แอปรัน WebSocket server ในตัวเองเพื่อ broadcast barcode ที่สแกนได้ไปยัง Tampermonkey script ใน browser (TikTok / Shopee / Odoo web) — เลิกต้องเปิดโปรเซสที่ 2

Class: `BarcodeBridgeWorker`

- port: `9999` (hardcoded)
- รันใน daemon thread แยก + asyncio event loop ของตัวเอง
- Qt thread เรียก `broadcast(barcode)` ซึ่ง schedule coroutine ผ่าน `asyncio.run_coroutine_threadsafe`
- broadcast **เฉพาะ `picking.origin`** ทันทีที่เจอใบ Pack ใน Odoo (ผ่าน signal `BarcodeWorker.origin_ready`) — ไม่สนว่าใบนั้นมีสินค้า 3g ที่รองรับหรือไม่
- ไม่ส่งตัวเลข barcode ที่ scanner ยิงมาดิบ ๆ
- skip broadcast ถ้า `origin` ว่าง / หา picking ไม่เจอใน Odoo / Odoo error
- Tampermonkey รับ origin เป็น raw string → `detectPlatform()` route ไป tab ที่ตรงกับ format (เช่น TikTok order ID → TikTok tab) ผ่าน cross-tab relay เดิม
- ไม่ดักคีย์เอง — re-use `GlobalBarcodeListener` ที่มีอยู่
- signal `status_changed(state, message)` → `lbl_bridge_status` ใต้ `lbl_odoo_status`:
  - `ok` + `"พร้อม (N tabs)"` (เขียว) — bind สำเร็จ + จำนวน browser tab ที่ connect
  - `fail` + `"port 9999 ถูกใช้แล้ว"` (แดง) — bind fail (เช่นเปิดโปรเซสเก่าค้าง)
- ปิดผ่าน `closeEvent` → `loop.call_soon_threadsafe(loop.stop)` (daemon thread จะตายเองตอน process exit)

Failure behavior:

- bind port fail → emit `fail` ไป UI, log stdout, แอปยังทำงาน counter ได้ปกติ (fail-soft)
- ไม่มี client connect → broadcast log `"no clients — barcode dropped"` แต่ไม่ error

Tampermonkey ฝั่ง browser:

- connect `ws://localhost:9999`
- รับ message เป็น barcode string ดิบ (ไม่มี JSON envelope)
- จัดการ filter / dispatch เอง (เช่น TikTok 18 หลัก vs Shopee alphanumeric)

## Userscript Logic (`combined-auto-print.user.js`)

Tampermonkey userscript ที่รันในเบราว์เซอร์ ฝั่งคู่กับ desktop app เพื่อ **auto-print ใบปะหน้า** บน Shopee / TikTok / Odoo / Lazada เมื่อได้รับเลข order

Metadata สำคัญ (header `==UserScript==`):

- `@version` ปัจจุบัน `2.11` — **ต้อง bump ทุกครั้งที่แก้ไฟล์นี้** เพราะ Tampermonkey ใช้เทียบ version ตอน auto-update
- `@match` ครอบ `seller.shopee.co.th`, `seller.tiktok.com`, `seller-th.tiktok.com`, `sellercenter.lazada.co.th` และ **`tdfb.odoo.com/odoo*`** (ทั้ง Odoo ไม่ใช่แค่ `/odoo/sales*`) — Odoo เป็น SPA, Tampermonkey inject เฉพาะตอน full load; ถ้า match แค่ `/odoo/sales*` แล้ว user soft-nav จาก `/odoo` เข้าไป จะไม่ถูก inject เลย (ดู ADR-0002)
- `@updateURL` / `@downloadURL` ชี้ไป `raw.githubusercontent.com/copter-TDFB/PJ-AI-count-sachet-in-packing-line/main/combined-auto-print.user.js` → Tampermonkey ดึง update จาก branch `main` โดยตรง (ต้อง commit + push ไฟล์นี้ขึ้น `main` ถึงจะ update ถึงเครื่อง user)
- `@grant GM_setValue / GM_addValueChangeListener` ใช้ทำ cross-tab relay

Input 3 ทางที่ trigger งาน (ทุกทางเรียก `handleOrderInput()`):

1. **WebSocket bridge** (`initScannerBridge`) — connect `ws://localhost:9999`, รับ barcode ดิบจาก desktop app (`BarcodeBridgeWorker` ส่ง `picking.origin` มา), reconnect อัตโนมัติทุก 3 วินาทีถ้า socket ปิด
2. **Ctrl+V paste** — ดัก paste event, อ่าน clipboard, ถ้า `detectPlatform()` รู้จัก format จะ preventDefault แล้วยิงงาน
3. **USB HID barcode scanner** — ดัก `keydown` ระดับ document; ตรวจ burst เร็ว (`SCANNER_GAP_MS = 80`), reset buffer ถ้าพิมพ์ช้า (= คนพิมพ์), trigger เมื่อกด Enter และ buffer length >= 6; skip ถ้า focus อยู่บน input/textarea

`detectPlatform(text)` route ตาม format ของเลข order:

- `^\d{18}$` → `tiktok`
- `^\d{16}$` → `lazada`
- `^S\d{4,6}$` หรือ `^MZS-\d+$` → `odoo` (เลข source document เช่น `S00123` หรือ `MZS-240278` — ตรงกับ `picking.origin` ที่ bridge ส่ง)
- `^[A-Z0-9]{6,25}$` ที่มีตัวอักษรปน → `shopee`
- ไม่ match → `null` (ไม่ทำอะไร)

Cross-tab relay logic (สำคัญ — เพราะแต่ละ platform เป็นคนละ tab/domain):

- `currentPlatform()` ดูจาก `location.hostname` ว่า tab นี้คือ platform ไหน
- ถ้า platform ของ order ตรงกับ tab ปัจจุบัน → run printing flow ของ platform นั้นเลย (`runTikTok` / `runShopee` / `runOdoo` / `runLazada`)
- ถ้าไม่ตรง → `GM_setValue('auto_print_job', {...})` แล้วโชว์ toast บอกให้สลับ tab
- ทุก tab subscribe `GM_addValueChangeListener('auto_print_job', ...)`; tab ที่ตรง platform จะ `window.focus()` แล้ว run flow เอง
- GM storage ทำงานข้าม domain ได้ จึง relay ระหว่าง Shopee/TikTok/Odoo/Lazada tab ได้แม้คนละ origin

Print flow ต่อ platform (`runXxx(orderNumber)`):

- ค้น search input ด้วย heuristic (`findSearchInput` / `findInputNearLabel`), set ค่าแบบ React-aware (`setReactValue`), กด Enter, รอ element ด้วย `waitFor` / `waitUntilEnabled`
- หา/กดปุ่มพิมพ์ (เช่น TikTok เลือก label A6), `hookWindowOpen()` ดัก `window.open` เพื่อ auto `print()` + `close()` หน้าต่าง label ที่เด้งมา
- Odoo เป็น 2 phase แต่ทำต่อเนื่องในหน้าเดียว: `odooPhase1` (ถ้า search bar ถูกยุบเหลือปุ่มแว่น กด `button .fa-search` เปิดก่อน — กดเฉพาะตอนหากล่อง `input.o_searchview_input` ไม่เจอ เพราะปุ่มเป็น toggle → ค้นหา → รอการ์ด Kanban/row ของ list ที่ข้อความตรงกับเลข order ด้วย selector รวม `.o_kanban_record, .o_data_row` แล้วคลิกใบนั้น → `waitForPath` รอ URL เป็น `/odoo/sales/<id>`) → เรียก `odooPhase2` ต่อทันที (กด gear → Print → ใบปะหน้า). `runOdoo` อ่าน `location.pathname` **สด ๆ ตอนถูกเรียก** จึง act เฉพาะหน้า Sales — สแกน/วางตอนอยู่หน้าอื่น (เช่น `/odoo` dashboard) จะ **เงียบสนิท ไม่ทำอะไรและไม่เตือน** (operator ต้องจอด Odoo tab ไว้ที่ `/odoo/sales*`). ไม่มีกลไก navigate ข้ามหน้า/`odoo_pending_job` อีกแล้ว (ลบออก v2.11 — ดู ADR-0002)
- มี jitter หน่วงเวลาแบบ human-feel (object `J`) ก่อนพิมพ์/คลิก/confirm

หมายเหตุการแก้ไข:

- ไฟล์นี้ **อยู่ใน git** (ไม่เหมือน model/zip ที่ ignore) — แก้แล้วต้อง commit + push `main` เพื่อให้ auto-update ถึง user
- ถ้าเพิ่ม platform ใหม่ ต้องแก้ `detectPlatform`, `currentPlatform`, `@match`, เพิ่ม `runXxx`, และ map ใน `handleOrderInput` + relay listener
- selector ของแต่ละ platform เปราะ (อิง DOM ของเว็บจริง) — เว็บอัปเดต UI เมื่อไหร่อาจพังเงียบ ๆ

## Detection Classes And Mapping

สี OBB ใน `_OBB_COLORS`:

- keyword `excellent` สีเขียวเข้ม
- keyword `medium` สีเขียว
- keyword `classic` สีเขียวอ่อน
- keyword `genmaicha` สีเขียวอมฟ้า
- keyword `houjicha` สีน้ำตาล
- อื่น ๆ ใช้เทา

Mapping สินค้าที่ detect แต่นอก order ให้แสดงชื่อ Odoo:

- `excellent` -> `Excellent Rich 95% 3.1g`
- `medium` -> `Medium Rich 95% 3.1g`
- `classic` -> `Classic Rich 95% 3.1g`
- `houjicha` -> `Houjicha Rich 95% 3.1g`
- `genmaicha` -> `Genmaicha Powder 3 g`

ถ้าเพิ่มสินค้าใหม่ ต้องแก้อย่างน้อย:

- Odoo search domain ใน `BarcodeWorker`
- `_KEYWORD_ODOO_NAME`
- `_OBB_COLORS` ถ้าต้องการสีเฉพาะ
- `_extract_keyword()` ใน `CounterPanel`
- ชื่อ class ใน training/model ต้องมี keyword ที่ match ได้

## `_draw_obb()` Logic

Input:

- BGR frame
- YOLO result
- model names
- crop rect normalized `(x, y, w, h)`

Logic:

1. คำนวณ crop rect เป็น pixel จาก frame size
2. สร้าง `out` เป็นภาพ crop copy เพื่อแสดงเฉพาะ counting zone
3. ถ้า `res.obb` มี detection:
   - ดึง polygon points `xyxyxyxy`
   - คำนวณ center ของ OBB ด้วย mean ของ 4 points
   - นับเฉพาะ object ที่ center อยู่ใน crop rect
   - translate polygon points ให้เข้ากับภาพ crop
   - draw polygon ด้วยสีตาม keyword
   - เพิ่ม count ตาม class name
4. คืน `(cropped_annotated, counts)`

ผลสำคัญ:

- model run บนภาพเต็มหลัง preprocess
- แต่การนับจริง filter ด้วย center-inside-crop
- ภาพที่แสดงใน popup เป็นภาพ crop zoom แล้ว ไม่ใช่ full frame
- รูป upload ไม่ใช้ crop ใน `CameraWorker.infer_image()` เพราะ user เลือกรูปเอง จึงนับทั้งภาพ

## CameraWorker Detailed Logic

Signals:

- `frame_ready(QImage, counts)` - ส่งภาพกล้อง annotated และ counts ไป UI
- `status_message(str)` - ส่งข้อความสถานะไป main window
- `model_ready(str)` - แจ้งชื่อ model ที่โหลดสำเร็จ
- `image_infer_done(QImage, counts)` - ผลจากรูป upload
- `image_infer_error(str)` - error จากรูป upload
- `raw_frame_ready(QImage)` - ภาพ pre-inference สำหรับ crop settings dialog

State:

- `model_path`
- `camera_id = 0`
- `conf`
- `_img_req` queue maxsize 1 สำหรับ one-shot image inference
- `_crop_rect`
- `_emit_raw` สำหรับ crop preview
- `_inference_enabled` เพื่อประหยัด CPU ตอนยังไม่มี order popup
- `_last_raw_frame` - frame ล่าสุดหลัง preprocess (ใช้สำหรับ snapshot ตอนนับครบ)
- `_running`

Model loading:

1. `pt_path = ai_3g_v12.pt`
2. `ov_path = ai_3g_v12_openvino_model`
3. ถ้า `.pt` และไม่มี OpenVINO dir:
   - emit status export OpenVINO
   - ลอง `YOLO(pt, task='obb').export(format='openvino', half=False)`
4. ถ้า OpenVINO dir มีอยู่:
   - ลองโหลด `YOLO(ov_path, task='obb')`
   - ถ้า fail fallback เป็น `YOLO(pt_path, task='obb')`
5. ถ้าไม่มี OpenVINO ใช้ `.pt`
6. **Warmup**: หลังโหลด model เสร็จจะ run inference บน dummy `np.zeros((640,640,3))` 5 ครั้ง — ลด latency รอบแรกของ user ตอนเปิด popup

Camera opening:

1. ลอง `cv2.VideoCapture(camera_id, cv2.CAP_MSMF)`
2. ถ้าเปิดไม่ได้ fallback เป็น `cv2.VideoCapture(camera_id)`
3. set width 1920
4. set height 1080
5. set buffer size 1

เหตุผลของ MSMF:

- ใช้ Windows Media Foundation Frame Server
- ช่วยแชร์กล้องกับ OBS หรือ app อื่นในบางเครื่องได้ดีกว่า backend default

Frame loop:

- main camera loop target ประมาณ 15 FPS
- อ่าน frame จาก camera
- flip horizontal ด้วย `cv2.flip(frame, 1)`
- ถ้า `_inference_enabled` หรือ `_emit_raw` เป็น true จะ push frame เข้า queue maxsize 1
- ถ้าไม่มี consumer จะไม่ push frame เพื่อประหยัด CPU
- UI frame emit เฉพาะเมื่อมี annotated result ใหม่ หรือยังไม่มีภาพแสดง

Inference thread `_infer()`:

- รันเป็น Python daemon thread ข้างใน `CameraWorker.run()`
- ใช้ model เดียวกับ camera และ image upload
- เช็ก image upload queue ก่อน
- แล้วเช็ก camera frame queue

Image upload inference:

- อ่านไฟล์ด้วย `Path(img_path).read_bytes()`
- decode ด้วย `cv2.imdecode`
- run `model(img_frame, conf=self.conf, verbose=False)`
- เรียก `_draw_obb(img_frame, res, model.names)` โดยไม่ส่ง crop rect จึงใช้ full crop
- emit `image_infer_done`

Camera frame preprocess:

1. ดู orientation จาก `w >= h`
2. ถ้า landscape ใช้ target aspect 16:9
3. ถ้า portrait ใช้ target aspect 9:16
4. center crop ให้ตรง aspect
5. downscale:
   - landscape และ height > 1080 -> resize 1920x1080
   - portrait และ width > 1080 -> resize 1080x1920
6. ถ้า `_emit_raw` true จะ emit raw frame หลัง preprocess ไป crop setting
7. ถ้า `_inference_enabled` false จะ skip inference
8. เก็บ `_last_raw_frame = frame` สำหรับ snapshot
9. run YOLO
10. `_draw_obb(frame, res, model.names, self._crop_rect)`
11. overlay FPS และ latency ลงภาพ
12. update shared `state` ให้ main loop emit UI

Snapshot logic:

- `save_snapshot(folder, filename)` เขียน `_last_raw_frame` ลง disk ใน daemon thread (ไม่ block UI)
- folder จะถูก `mkdir(exist_ok=True)` ทุกครั้ง
- ถูกเรียกจาก `MainWindow._on_snapshot_requested()` เมื่อ `CounterPanel` emit `snapshot_requested(picking_name)` ตอนนับครบ
- ชื่อไฟล์: `<YYYY-MM-DD_HH-MM-SS>_<sanitized_picking_name>.png`

CPU optimization:

- ตอนยังไม่มี order popup `_inference_enabled = False` (default)
- app ยังเปิดกล้องได้ แต่ไม่ run YOLO
- frame ก็ไม่ถูก push เข้า queue เลย เว้นแต่ crop preview เปิดอยู่
- เมื่อ scan barcode สำเร็จ `MainWindow._on_barcode_data()` set inference true
- เมื่อปิด counter popup `_on_counter_closed()` set inference false

## Crop Settings UI

เปิดจากปุ่มเฟืองใน `MainWindow`

Flow:

1. อ่าน `cur_rect` และ `cur_conf` จาก `CameraWorker`
2. สร้าง `CropSettingsDialog`
3. set `_emit_raw = True` เพื่อให้ CameraWorker ส่ง raw frame preview
4. user ลากกรอบบนภาพเพื่อเลือก counting zone
5. user เลื่อน confidence slider 0.05..0.95
6. ถ้ากด save:
   - `CameraWorker.set_crop_rect(new_rect)`
   - `CameraWorker.set_conf(new_conf)`
   - `_save_settings(new_rect, new_conf)` ลง `crop_config.json`
7. disconnect preview signal และ set `_emit_raw = False`

`CropPreviewWidget`:

- แปลง mouse position เป็น normalized image coordinate
- drag เพื่อสร้าง rect
- ถ้ากรอบเล็กกว่า 0.05 ของภาพ จะ reset เป็น full crop
- paint image, dark overlay นอก crop, และเส้นขอบ crop

Confidence slider:

- range 5..95
- value แสดงเป็น `conf = 0.xx`
- default จาก `CameraWorker.conf`

## CounterPanel Logic

หน้าที่:

- แสดงภาพกล้องหรือรูป upload
- แสดงรายการสินค้า, demand, lot, expiration date จาก Odoo
- เปรียบเทียบ AI count กับ demand
- แจ้งเตือนขาด/เกิน/สินค้านอก order
- เล่นเสียง, shake หน้าต่าง, snapshot, post log เมื่อถูกต้อง

State สำคัญ:

- `_current_entry` - picking + moves ปัจจุบัน (รวม `lots_by_product`)
- `_product_rows` - list ของ card UI และข้อมูลสินค้า
- `_last_class_counts` - counts ล่าสุดจาก model
- `_log_posted` - กัน post Odoo ซ้ำในใบเดียว (set true ทันทีที่ snapshot/toast trigger เพื่อกัน race)
- `_pending_product_counts` - snapshot ของ counts ตอนนับครบ; จะใช้ตอน `_save_to_odoo()` ใน `hideEvent`
- `_stable_since` - timestamp ที่ counts เริ่มนิ่ง
- `_last_stable_counts` - key สำหรับ detect ว่าจำนวนเปลี่ยนไหม
- `_last_sound_status` - กันเล่นเสียงซ้ำตอน status เดิม
- `_image_mode` - true เมื่อกำลังแสดงผลจากรูป upload
- `_save_workers` - เก็บ save worker ไม่ให้ถูก GC
- `_shake_*` - state ของ MSN-style nudge animation

Signals:

- `closed` - emit ตอน `hideEvent`
- `image_infer_requested(str)` - request inference จากรูป upload
- `snapshot_requested(str picking_name)` - ขอให้ camera worker snapshot frame ปัจจุบัน

Popup flow:

1. `popup(entry)` รับ picking + moves + lots_by_product
2. set `_current_entry`
3. แสดง picking name, partner, state
4. `_build_count_table(moves, lots_by_product)` สร้าง card ตามสินค้าใน order
5. `_fit_to_screen()` ปรับขนาดให้พอดีจอ
6. show, activate, raise, และลอง `SetForegroundWindow`

`_fit_to_screen()`:

- ดูจอที่หน้าต่างอยู่ผ่าน `QApplication.screenAt(self.pos())` (fallback `primaryScreen()`)
- ใช้ 90% ของ `availableGeometry` แต่ไม่เกิน design size 1380×800
- minimum 900×560
- center popup บนจอนั้น

Card building:

- `product_id[1]` ถูก clean ด้วย `_strip_ref()`
- keyword จาก `_extract_keyword()`:
  - excellent
  - medium
  - classic
  - houjicha
  - genmaicha
  - fallback เป็น word แรก
- card แสดง:
  - product name
  - counted / demand
  - status badge
  - Lot + EXP row (สีเขียวมิ้นต์) — แสดง lot names dedupe + วันหมดอายุในรูปแบบ `dd/MM/yyyy`; ถ้าไม่มี lot แสดง `Lot: -`
- `_fit_cards_to_viewport()` พยายาม fit card 5 slots ใน scroll viewport (ปรับ fixed height ตามขนาด viewport)
- `_cards_scroll` ถูก set `HorizontalScrollBarPolicy = ScrollBarAlwaysOff` ป้องกัน scroll แนวนอน

Update flow:

- camera mode: `update_frame(qimg, class_counts)`
  - ถ้า `_image_mode` true จะ ignore camera frames
  - แสดงภาพ
  - `_apply_counts(class_counts, stable_check=True)`
- image mode: `_on_image_result(qimg, class_counts)`
  - set `_image_mode = True`
  - แสดงภาพ
  - `_apply_counts(class_counts, stable_check=False)`
  - แสดงปุ่มกลับกล้อง

Counting comparison:

สำหรับสินค้าแต่ละตัวใน order:

- `cnt = _get_count(class_counts, keyword)`
- `demand = int(product_uom_qty)`
- ถ้า `cnt == demand`:
  - สีเขียว
  - status ครบแล้ว
- ถ้า `cnt > demand`:
  - สีแดง
  - status เกิน
  - `any_over = True`
  - เพิ่ม alert line
- ถ้า `cnt < demand`:
  - สีส้ม
  - status ขาด
  - เพิ่ม alert line

Wrong product detection:

- สร้าง set ของ keyword ที่อยู่ใน order
- ถ้า class_counts มี class ที่ count > 0 แต่ class name ไม่มี keyword ใน order:
  - ถือว่าเป็นสินค้านอก order
  - set `all_exact = False`
  - set `any_over = True`
  - แสดง `lbl_wrong`
  - เพิ่ม alert line

Persistent alert:

- ถ้ามี product rows, มีของถูก detect แล้ว, และไม่ exact:
  - `_show_alert("ไม่ตรงตาม Order" + รายการขาด/เกิน/นอก order)` แสดงกลางจอ (`_position_alert` วางแนวกลาง vertical/horizontal)
- ถ้าตรงหรือยังไม่มีของ detect:
  - hide alert

Stability logic:

- สร้าง `stability_key = (current_counts, wrong_counts)`
- ถ้า key เปลี่ยน:
  - reset `_stable_since = now`
  - reset `_last_sound_status = None`
- camera mode ต้องรอ counts นิ่งอย่างน้อย 0.5 วินาที ก่อนเล่นเสียงหรือ trigger save
- image mode ไม่รอ 0.5 วินาที เพราะเป็นภาพนิ่ง

Sound/status:

- ถ้า exact -> `status_key = "exact"` -> เล่น `ถูก.mp3`
- ถ้า over หรือ wrong product -> `status_key = "over"` -> เล่น `ผิด.mp3`
- ถ้า under -> `status_key = "under"` -> เล่น `ผิด.mp3`
- เล่นเสียงด้วย Windows MCI ผ่าน `ctypes.windll.winmm.mciSendStringW`
- ใช้ alias ใหม่ทุกครั้งด้วย `_snd_counter`

Shake (MSN-style nudge):

- ถ้า status ไม่ exact จะเรียก `_shake_window()`
- amplitude เริ่ม 16 px และ decay แบบ damped oscillation 15 step (เคลื่อนทุก 22 ms)
- ระหว่าง shake ถ้าโดน trigger ซ้ำจะ snap หน้าต่างกลับ origin ก่อนเริ่มใหม่
- คืน position เดิมเสมอเมื่อจบ

Auto-save flow (สำคัญ — เปลี่ยนไปจากเดิม):

เมื่อเข้าเงื่อนไข `all_exact` ครั้งแรก:

1. set `_log_posted = True` (กัน trigger ซ้ำ)
2. snapshot `_pending_product_counts` จาก `_product_rows`
3. emit `snapshot_requested(picking_name)` — main window ส่งต่อให้ camera worker save PNG ใน background
4. แสดง toast `✓ ครบตามจำนวนใน order` (สีเขียว, success=True)
5. start `_hide_timer` (1.5 วินาที) แล้ว popup hide เอง
6. ใน `hideEvent` จะเรียก `_save_to_odoo()` → spawn `OdooSaveWorker` post note
7. ถ้า save fail → log ลง stdout เท่านั้น ไม่มี toast แสดงให้ user เห็น (เพราะ popup ปิดแล้ว)
8. ถ้าผู้ใช้กดปิด popup เองก่อน timer หมด ก็ยัง trigger save จาก `hideEvent` (ถ้ามี pending_product_counts)

Reason: ก่อนหน้านี้ save ทำหน้า popup ค้าง รอจน Odoo ตอบ ทำให้ flow ดูช้า — เปลี่ยนมา fire-and-forget แทน user perception เร็วขึ้นเยอะ

Close behavior:

- เมื่อ popup hide จะเรียก `_save_to_odoo()` (ถ้ามี pending) แล้ว emit `closed`
- `MainWindow._on_counter_closed()` จะ:
  - disable camera inference
  - enable barcode listener
  - reset icon/status เป็นพร้อม scan ใบใหม่

## MainWindow Logic

Startup:

1. สร้าง `CounterPanel`
2. สร้าง `GlobalBarcodeListener`
3. build UI
4. start `CameraWorker(DEFAULT_MODEL)`
5. start `OdooStatusWorker`
6. spawn daemon thread เรียก `OdooConn.ensure()` pre-warm
7. connect focusChanged เพื่อ suppress global barcode listener เมื่อ app focus

UI:

- หน้าหลัก fixed width 600
- barcode input + icon status + ปุ่ม crop settings (row บน)
- label Odoo connection status (`lbl_odoo_status`) ใต้ row barcode
- label status model/camera/barcode (`lbl_status`)

Barcode scan flow:

1. user scan หรือกด Enter ใน textbox
2. `_on_barcode_scanned(barcode)`
3. set icon เป็น loading
4. สร้าง `BarcodeWorker`
5. worker success -> `_on_barcode_data(entry)`
6. worker not found -> `_on_not_found(msg)`
7. worker error -> `_on_error(msg)` และสั่ง Odoo status worker `check_now()` ทันที

เมื่อเจอ data:

- icon success
- status แสดง picking name
- barcode listener inactive
- camera inference enabled
- open counter popup

Snapshot bridge:

- connect `counter_panel.snapshot_requested` → `_on_snapshot_requested(picking_name)`
- sanitize picking_name (เฉพาะ alnum / `-` / `_`, อื่น ๆ แทนด้วย `_`)
- เรียก `camera_worker.save_snapshot(_get_base_dir() / 'snapshots', filename)`

Odoo status update:

- `_on_odoo_status(state, msg)` ปรับสี label:
  - `ok` → เขียว `#4CAF50`
  - `fail` → แดง `#EF5350`
  - `checking` → เหลือง `#FFB300`

Close app:

- stop global barcode listener
- stop Odoo status worker
- stop camera worker
- close counter panel

## Batch Evaluator (`batch_eval_app.py`)

หน้าที่:

- โหลด model
- เลือก dataset folder
- run inference ทุกภาพ
- ถ้ามี YOLO labels จะคำนวณ metrics
- export CSV ได้

Default:

- `DEFAULT_MODEL = ai_3g_v12.pt`
- image extensions: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`, `.tiff`, `.tif`
- default conf ใน batch UI เริ่มที่ `0.50` (ตั้งใจให้ต่างจาก runtime 0.7 เพื่อให้เห็น false positives ตอนประเมิน)

Dataset scan:

- `collect_images(folder)` หา split `train` และ `val` ก่อน
- รองรับ:

```text
dataset/
  train/images/
  train/labels/
  val/images/
  val/labels/
```

และ:

```text
dataset/
  train/
  val/
```

- ถ้าไม่เจอ train/val จะ scan รูปทุกไฟล์ใต้ root และใช้ split เป็น `root`

Label finding:

`find_label_file(image_path)` ตรวจตามลำดับ:

1. same directory: `<image_dir>/<stem>.txt`
2. path pattern จาก parent/labels/image_folder_name
3. replace path segment `images` เป็น `labels`

ข้อควรจำ:

- YOLO standard `train/images/x.jpg` -> `train/labels/x.txt` ถูกครอบคลุมโดย rule 3
- ถ้า label ไม่เจอ ภาพนั้นยัง run ได้ แต่ไม่มี GT metric

ModelLoader:

- ถ้า `.pt` และไม่มี OpenVINO dir จะพยายาม export OpenVINO
- ถ้ามี OpenVINO dir จะโหลด OpenVINO ด้วย `task='obb'`
- ถ้า OpenVINO fail fallback `.pt`

BatchWorker:

- อ่านภาพด้วย `np.fromfile` + `cv2.imdecode` เพื่อรองรับ path ภาษาไทย/Unicode
- run `model(frame, conf=self.conf, verbose=False)`
- count class จาก `res.obb.cls`
- ถ้ามี label จะ parse GT count จาก class id -> model.names
- emit result ทีละภาพ

Metrics:

- ต่อ split และ class:
  - `GT Total`
  - `Pred Total`
  - `MAE = mean(abs(pred - gt))`
  - `Count Acc % = % ของภาพที่ pred == gt`
  - `Avg Diff = mean(pred - gt)` บวกคือ over-detect ลบคือ under-detect
- overall:
  - รวม exact flags และ abs errors ของทุก image/class pair ที่มี label

CSV export columns:

- `split`
- `filename`
- `class`
- `gt_count`
- `pred_count`
- `diff`
- `latency_ms`
- `conf`

## Build Logic (`build.ps1`)

Input:

```powershell
.\build.ps1 <Version>
```

ถ้าไม่ส่ง version จะใช้ `0.0.0`

Steps:

1. set working dir เป็น script root
2. ลบ `build/`, `dist/`, `dist_release/`
3. build main app:
   - `python -m PyInstaller --noconsole --onedir --name odoo_counter`
   - collect all `ultralytics`, `PyQt6`, `cv2`, `openvino`
   - exclude `PySide6`, `PyQt5`, `shiboken6`
4. build launcher:
   - `python -m PyInstaller --noconsole --onefile --name launcher`
   - **`--hidden-import truststore`** — PyInstaller scan ไม่เจอ import แบบ try/except
   - **`--collect-all certifi`** — bundle CA bundle data ด้วย
5. create `dist_release/app`
6. copy `dist/odoo_counter/*` ไป `dist_release/app/`
7. copy `ai_3g_v12.pt`
8. copy `ai_3g_v12_openvino_model/` ถ้ามี (ถ้าไม่มี print warning)
9. copy `*.mp3`
10. copy `dist/launcher.exe` ไป `dist_release/launcher.exe`
11. เขียน `dist_release/app/version.txt` ด้วย `[System.IO.File]::WriteAllText` + `UTF8Encoding $false` → UTF-8 no BOM

เหตุผลที่เขียน version ด้วย .NET API:

- PowerShell 5.1 `Out-File -Encoding utf8` ใส่ BOM
- BOM เคยทำให้ `parse_version` ใน launcher พัง (และ `get_local_version()` แม้จะใช้ `utf-8-sig` แล้ว แต่กันไว้สองชั้น)

## Release Logic (`release.ps1`)

Input:

```powershell
.\release.ps1 1.2.0 "release notes"
```

Steps:

1. refresh PATH จาก registry เพื่อให้เจอ `gh` แม้ terminal session เก่า
2. run `build.ps1`
3. zip ด้วย `tar -caf odoo-counter-<version>.zip -C dist_release app`
4. upload GitHub release:
   - tag `v<version>`
   - title `v<version>`
   - notes จาก argument
   - asset คือ zip

สำคัญ:

- zip ต้องมี folder `app/` เป็น root
- launcher download asset `.zip` แรกใน latest release
- ถ้ามีหลาย zip ใน release ล่าสุด อาจเลือกผิดได้ เพราะ launcher หา asset แรกที่ suffix เป็น `.zip`

## Changing Model Version Checklist

ถ้าเปลี่ยนจาก v12 ไป v13:

1. วาง `ai_3g_v13.pt` ใน root
2. export OpenVINO เป็น `ai_3g_v13_openvino_model/` ถ้าต้องการ startup เร็ว
3. แก้ `DEFAULT_MODEL` ใน `odoo_counter_app.py`
4. แก้ `DEFAULT_MODEL` ใน `batch_eval_app.py`
5. แก้ `build.ps1` ให้ copy `ai_3g_v13.pt`
6. แก้ `build.ps1` ให้ copy `ai_3g_v13_openvino_model`
7. แก้ doc string ใน `launcher.py` (เฉพาะ comment example layout, ไม่กระทบ runtime)
8. ทดสอบ `python odoo_counter_app.py`
9. ทดสอบ `python batch_eval_app.py` กับ dataset เล็ก
10. ทดสอบ `.\build.ps1 <version>` และเปิด `dist_release\launcher.exe`
11. release ด้วย `release.ps1`

## Adding New Product Checklist

ถ้าต้องเพิ่มสินค้าใหม่:

1. ตรวจชื่อ product ใน Odoo ให้ตรงจริง
2. ตรวจ class name จาก YOLO model ว่ามี keyword ที่ใช้ match ได้
3. เพิ่ม product domain ใน `BarcodeWorker`
4. เพิ่ม keyword ใน `_KEYWORD_ODOO_NAME`
5. เพิ่ม keyword ใน `_extract_keyword()`
6. เพิ่มสีใน `_OBB_COLORS` ถ้าต้องการ
7. ทดสอบใบ pack ที่มีสินค้าใหม่
8. ทดสอบกรณีสินค้าใหม่อยู่นอก order ว่า wrong product alert ขึ้นถูก
9. ทดสอบ post note ใน Odoo

## Troubleshooting

Launcher เปิดไม่ได้หรือไม่ update:

- ดู `launcher.log`
- เช็ก internet และ SSL — ถ้า log บอก `CERTIFICATE_VERIFY_FAILED` ตรวจว่า build ได้ `--hidden-import truststore` และ `--collect-all certifi` หรือไม่
- เช็ก GitHub Release ล่าสุดว่ามี asset `.zip`
- เช็กว่า zip มี root `app/`
- เช็ก `app/version.txt` — ถ้ามี BOM, `get_local_version()` ใช้ `utf-8-sig` แล้ว แต่ `parse_version` ก็ strip `﻿` กันชั้นสองอยู่

App เปิดแล้วหา model ไม่เจอ:

- เช็กว่า `ai_3g_v12.pt` อยู่ข้าง exe/source
- ใน build output ต้องอยู่ `dist_release/app/ai_3g_v12.pt`
- ถ้าเปลี่ยน model version ต้องแก้ทั้ง source และ `build.ps1`

OpenVINO fail:

- app จะ fallback ไป `.pt`
- startup อาจช้าขึ้น
- ถ้าใน exe export OpenVINO fail บ่อย ให้ pre-export แล้ว copy folder เข้า release

Camera ไม่ขึ้น:

- code ใช้ camera id 0
- ลองปิด app อื่นที่ใช้กล้อง
- code ใช้ MSMF ก่อนแล้ว fallback default
- resolution ถูก set 1920x1080 แต่บางกล้องอาจไม่รับจริง
- ตอนนี้รองรับทั้ง landscape (16:9) และ portrait (9:16) — ตัดสินจาก orientation ของ raw frame

Count ไม่ตรง:

- เช็ก crop zone ในปุ่ม setting
- เช็ก confidence threshold
- เช็กว่า class name ของ model มี keyword ที่ `_extract_keyword()` match ได้
- เช็กว่าสินค้าใน Odoo move name ตรง domain ที่ `BarcodeWorker` search
- ใช้ `batch_eval_app.py` กับรูป/label เพื่อดู over/under
- ดู `snapshots/` เพื่อย้อนภาพที่ trigger save — ตอบโจทย์ post-mortem ว่านับครบจริงไหม

Scan barcode ไม่ติด (โดยเฉพาะตอน Windows อยู่ในโหมดไทย):

- VK_MAP ใหม่ map virtual-key code ตรง → bypass IME แล้ว
- ถ้ายังไม่ติด เช็กว่า scanner ส่ง keystroke แบบ HID keyboard ปกติ (ไม่ใช่ raw serial)
- scanner ต้องส่ง Enter ท้าย barcode
- barcode length ต้อง >= 4
- ถ้าพิมพ์ช้ามาก global listener อาจ reset เพราะ timeout 0.15s

Post Odoo ไม่สำเร็จ:

- toast สำเร็จที่ user เห็นไม่ได้แปลว่า post จริงสำเร็จ — เพราะ flow ใหม่ optimistic
- ดู Odoo status label ใต้ barcode input
- error จะ print ลง stdout เท่านั้น (`[Odoo] บันทึกไม่สำเร็จ: ...`) — รัน exe จาก console ถ้าต้อง debug
- worker จะ reset OdooConn เมื่อ error
- ตรวจ credential ใน source
- ตรวจว่า user มีสิทธิ์ `message_post` บน picking

Lot/EXP ไม่ขึ้น:

- บางใบใน Odoo ยังไม่ assign lot → `stock.move.line` ไม่มี `lot_id` หรือ `lot_name` → card จะแสดง `Lot: -`
- ถ้า Odoo เป็นรุ่นเก่ามาก code ลอง `stock.lot` ก่อน fallback `stock.production.lot` — ถ้า model ทั้งสองไม่มี exp จะเป็น string ว่าง

Batch evaluator ไม่มี accuracy:

- label `.txt` อาจอยู่ผิด path
- model.names class id ต้องตรงกับ label class id
- ถ้าไม่มี label app จะแสดงแค่ predicted counts

## Git And Working Tree Notes

ตอนสำรวจวันที่ 2026-05-30 worktree มีไฟล์ที่แก้หรือ untracked อยู่:

- modified: `batch_eval_app.py`, `build.ps1`, `launcher.py`, `odoo_counter_app.py`
- untracked: `AGENTS.md`, `PROJECT_CONTEXT.md`, `ai_3g_v9.pt`, `ai_3g_v10.pt`, `ai_3g_v11.pt`, `ai_3g_v12.pt`, `สูตร upload เข้า githup.txt`

Commit history:

- `89da592 feat: counting zone crop, conf threshold, persistent alert`
- `ff3844d initial commit`

→ การเปลี่ยนแปลงส่วนใหญ่ใน working tree ปัจจุบัน (lot/exp lookup, OdooStatusWorker, snapshot, shake, warmup, VK-map, OpenVINO v12, SSL launcher) **ยังไม่ commit** แต่ release v1.1.x ที่ขึ้น GitHub Release แล้วน่าจะ build จาก state นี้ — ก่อนแก้ไฟล์เหล่านี้ระวังว่าจะกระทบ release ที่ user ใช้อยู่

ข้อควรทำ:

- อย่า `git reset --hard`
- อย่า revert ไฟล์ที่ user แก้อยู่ ถ้า user ไม่ได้สั่ง
- ก่อนแก้ไฟล์ใหญ่ให้ดู diff เฉพาะจุด
- ไฟล์โมเดลและ zip ใหญ่มาก ระวัง commit โดยไม่ตั้งใจ

`.gitignore` ปัจจุบัน ignore:

- `__pycache__/`
- `*.pyc`
- `build/`
- `dist/`
- `dist_release/`
- `*.spec`
- `update_tmp/`
- `launcher.log`
- `*_openvino_model/`
- `*.zip`
- `app_backup/`
- `crop_config.json`

หมายเหตุ:

- ถึง `.gitignore` ignore `crop_config.json` แต่ไฟล์อาจมีอยู่ local และมีผลกับ default conf/crop
- ถึง ignore `*_openvino_model/` แต่ build ต้องใช้ folder นี้ถ้าต้องการ bundle OpenVINO pre-exported
- โฟลเดอร์ `snapshots/` **ไม่ได้** ถูก ignore — ถ้ารัน source mode ในโปรเจกต์ root โฟลเดอร์นี้จะถูกสร้างขึ้นและอาจหลุดเข้า git ตอน add ทั้งหมด

## Safe Edit Guidelines For Future AI

ก่อนเริ่มแก้:

1. อ่าน `PROJECT_CONTEXT.md`
2. เช็ก `git status --short`
3. ถ้าจะแก้ app หลัก อ่านส่วนที่เกี่ยวข้องใน `odoo_counter_app.py`
4. ถ้าแก้ model/version ต้องแก้ทั้ง app, batch evaluator, และ build script
5. ถ้าแก้ release/update ต้องอ่าน `launcher.py`, `build.ps1`, `release.ps1` พร้อมกัน

เวลาทดสอบ:

- logic pure/config ใช้การอ่าน diff หรือรัน import ถ้าทำได้
- UI/camera/Odoo ต้องระวัง dependency, hardware, internet, credential
- ถ้าไม่ได้รันทดสอบจริง ให้บอก user ตรง ๆ

อย่าทำ:

- อย่าใส่ password จริงเพิ่มใน docs
- อย่า delete zip/model/build output โดยไม่ถาม
- อย่าเปลี่ยน product matching แบบกว้างเกินจนสินค้าอื่น match ผิด
- อย่าเปลี่ยน zip structure เพราะ launcher คาดหวัง `app/`
- อย่ายัด `_save_to_odoo()` กลับไปทำใน main flow (ก่อน hide) — flow ปัจจุบันจงใจ async เพื่อ UX

## Quick Reference: Key Classes

`launcher.py`

- `Launcher` - UI + update + launch app
- `_make_ssl_context()` - truststore → certifi → default

`odoo_counter_app.py`

- `OdooConn` - XML-RPC connection cache
- `BarcodeWorker` - search picking/moves + lot/exp lookup
- `OdooSaveWorker` - post Odoo note (fire-and-forget จาก hideEvent)
- `_PingTransport` - XML-RPC timeout transport
- `OdooStatusWorker` - periodic Odoo ping + `check_now()` event-based wakeup
- `BarcodeBridgeWorker` - WebSocket server (port 9999) broadcast barcode ไป Tampermonkey ใน browser
- `GlobalBarcodeListener` - global scanner listener (VK-based, IME bypass)
- `CameraWorker` - model/camera/inference/warmup/snapshot
- `CropPreviewWidget` - crop drawing widget
- `CropSettingsDialog` - crop/conf dialog
- `CounterPanel` - counting popup + shake + lot/exp UI + fit-to-screen
- `MainWindow` - main barcode window + Odoo status indicator + snapshot bridge

`batch_eval_app.py`

- `ModelLoader` - load/export model
- `BatchWorker` - run dataset inference
- `FolderDropZone` - drag/drop folder
- `BatchEvalWindow` - batch UI
