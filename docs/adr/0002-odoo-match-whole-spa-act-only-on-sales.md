# Odoo: `@match` ครอบทั้ง `/odoo*` แต่ทำงานเฉพาะหน้า Sales

Odoo web client เป็น SPA — เปลี่ยนหน้าด้วย `history.pushState` โดยไม่ reload. Tampermonkey ตัดสินใจ inject userscript **เฉพาะตอน full document load** เท่านั้น. เดิม `@match` เป็น `https://tdfb.odoo.com/odoo/sales*` ทำให้ user ที่เปิด Odoo มาที่ `/odoo` (dashboard) แล้ว soft-nav เข้า `/odoo/sales` ไม่เคยถูก inject เลย (URL เปลี่ยนแต่ไม่มี full load) — script ตายเงียบจนกว่าจะ F5. เราจึงขยาย `@match` เป็น `https://tdfb.odoo.com/odoo*` ให้ script โหลดตั้งแต่หน้าแรกแล้วอยู่ยาวข้าม soft-nav (paste/WS/relay listener ผูกครั้งเดียว ไม่หลุด), และให้ `runOdoo` อ่าน `location.pathname` สด ๆ ตอนถูกเรียกเพื่อ act **เฉพาะ** หน้า `/odoo/sales*`.

## Considered Options

- **คง `@match` แคบ `/odoo/sales*` (rejected).** ตรงเป้าที่สุดบนกระดาษ แต่พังกับ SPA: หน้าแรกที่โหลดคือ `/odoo` ไม่ match → ไม่ inject → soft-nav เข้า sales ก็ไม่ inject. ต้อง F5 ทุกครั้ง = ใช้งานจริงไม่ได้.
- **`@match` แคบ + เก็บ `odoo_pending_job` แล้ว `location.href='/odoo/sales'` ให้ full reload (เดิม, rejected).** เคยมีกลไกนี้ แต่มันจะถูกเรียกได้ต่อเมื่อ script ถูก inject บนหน้าตั้งต้นก่อน ซึ่งบน `/odoo` มันไม่ถูก inject เลย → ไปไม่ถึงกลไก. ซับซ้อนเกินจำเป็นเมื่อขยาย match แล้ว.
- **`@match` ทั้ง host `/*` (rejected).** ครอบ login/หน้าอื่น ๆ กว้างเกินจำเป็น.
- **`@match /odoo*` + act เฉพาะ Sales (chosen).** script มีชีวิตตั้งแต่ `/odoo`, อยู่ยาวข้าม soft-nav, แต่ลงมือทำงานเฉพาะหน้า Sales เพราะ `runOdoo` อ่าน path สด.

## Consequences

- **ลบกลไก `odoo_pending_job` + auto-navigate ทั้งชุดออก** (ทั้งตัวเซ็ต job และ reactive pickup IIFE) รวมถึง `@grant GM_getValue` ที่ไม่ใช้แล้ว — กลายเป็น dead code เพราะไม่มี navigate ข้ามหน้าอีก.
- **operator ต้องจอด Odoo tab ไว้ที่ `/odoo/sales` (list) หรือหน้า order ตอนสแกน.** ถ้าเผลออยู่หน้าอื่นแล้วสแกน → **ไม่ทำอะไรและไม่มีสัญญาณเตือนใด ๆ** (ตั้งใจให้เงียบ). เวลามันไม่ปริ้น สาเหตุอันดับแรกคือ tab อยู่ผิดหน้า.
- script จะถูก inject บนทุกหน้า `/odoo*` (รวม dashboard/inventory) — WS bridge เชื่อมต่อทุกหน้า ซึ่ง benign: ไม่มีอะไรเกิดจนกว่าจะได้รับ order บนหน้า Sales.
- ถ้าอนาคต Odoo เปลี่ยน base path ออกจาก `/odoo/*` (เช่น กลับไป legacy `/web#...`) ต้องอัปเดต `@match` และ regex path ใน `runOdoo`.
