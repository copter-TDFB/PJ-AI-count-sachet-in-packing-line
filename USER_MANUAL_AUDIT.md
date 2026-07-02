# Audit: USER_MANUAL.html

## Audit Health Score

| # | Dimension | Score | Key Finding |
|---|---|---:|---|
| 1 | Accessibility | 2/4 | สีข้อความหลักอ่านง่าย แต่ไม่มี landmarks, `scope` ในตาราง และโครงสร้างรูปภาพเชิง semantic |
| 2 | Performance | 4/4 | Static HTML ขนาดเล็ก ไม่มี JavaScript หรือ asset หนัก |
| 3 | Responsive Design | 2/4 | Grid รูปลดเหลือหนึ่งคอลัมน์ได้ แต่ตารางและ A4-first cover ยังเสี่ยงล้น/ยาวเกินบนจอแคบ |
| 4 | Theming | 1/4 | ใช้สี hard-code 64 ครั้ง รวม 33 สี และไม่มี design tokens |
| 5 | Anti-Patterns | 1/4 | ฟอนต์ระบบทั่วไป, corporate navy/yellow, กล่องเส้นประซ้ำ และเลข 01–26 ให้ภาพแบบ template AI |
| **Total** | | **10/20** | **Acceptable: ต้องปรับระบบภาพครั้งใหญ่** |

## Anti-Patterns Verdict

**Fail.** หน้าปัจจุบันดูเหมือนเอกสาร A4 ที่ถูกแปลงเป็นเว็บ มากกว่าคู่มือดิจิทัลที่ออกแบบมาเพื่อพนักงานหน้างาน สัญญาณที่ชัดคือหัวข้อสีน้ำเงินซ้ำ, ตารางเต็มหน้า, ฟอนต์ Leelawadee UI, กล่อง placeholder แบบเดียวกัน 26 จุด และหมายเลขวงกลม 01–26 ซึ่ง detector ของ Impeccable ระบุว่าเป็น numbered-section scaffold

## Executive Summary

- Audit Health Score: **10/20 (Acceptable)**
- Issues: **P0 0, P1 2, P2 6, P3 2**
- จุดที่ดี: `lang="th"`, body contrast 16.27:1, muted text 6.32:1, มี print page size, สถานะไม่ได้อาศัยสีอย่างเดียว, และไฟล์เบา
- สิ่งที่ต้องทำก่อน: แยก web layout ออกจาก print layout, สร้าง semantic structure, เปลี่ยนระบบตัวอักษร, ลดการ์ดซ้ำ และรวมสีเป็น tokens

## Detailed Findings

### [P1] ตารางและ flow ไม่มี mobile containment

- **Location:** `USER_MANUAL.html:19-23`, `29-31` และตาราง 6 จุด
- **Category:** Responsive Design
- **Impact:** ตารางกว้างและ flow 4 ขั้นอาจถูกตัดหรือทำให้เลื่อนแนวนอนบนจอแคบ พนักงานจะพลาดคอลัมน์ “สิ่งที่ต้องทำ” ซึ่งเป็นข้อมูลสำคัญที่สุด
- **Standard:** WCAG 1.4.10 Reflow
- **Recommendation:** ห่อ table ด้วย container ที่ scroll ได้, เปลี่ยนตารางสำคัญเป็น stacked rows บนมือถือ และให้ flow เปลี่ยนเป็นแนวตั้ง
- **Suggested command:** `$impeccable adapt USER_MANUAL.html`

### [P1] โครงสร้าง semantic ไม่เพียงพอ

- **Location:** ทั้งเอกสาร; พบ `<main>`, `<nav>`, `<aside>` เท่ากับ 0 และ `<th scope>` เท่ากับ 0
- **Category:** Accessibility
- **Impact:** Screen reader และเครื่องมือช่วยอ่านไม่สามารถข้ามไปเนื้อหาหลักหรือเข้าใจความสัมพันธ์หัวตารางได้ดี
- **Standard:** WCAG 1.3.1, 2.4.1
- **Recommendation:** เพิ่ม skip link, `<main>`, navigation สารบัญ, `<figure>/<figcaption>`, และ `scope="col"` ให้ทุกหัวตาราง
- **Suggested command:** `$impeccable harden USER_MANUAL.html`

### [P2] หน้าเว็บถูกออกแบบด้วยตรรกะกระดาษ A4

- **Location:** `USER_MANUAL.html:23-25`
- **Category:** Responsive / Anti-Pattern
- **Impact:** Cover สูง `250mm` ทำให้จอมีพื้นที่ว่างมาก และเนื้อหาไม่มี navigation ที่เหมาะกับเอกสารยาว
- **Recommendation:** ทำ web-first shell มี sticky contents rail และ content width 68–74ch; ย้าย `mm`, page break และการแบ่งหน้าไปไว้ใน `@media print`
- **Suggested command:** `$impeccable layout USER_MANUAL.html`

### [P2] ไม่มีระบบ theme

- **Location:** CSS ทั้งไฟล์; สี hard-code 64 ครั้ง รวม 33 สี
- **Category:** Theming
- **Impact:** เปลี่ยนบุคลิกยาก สีสถานะและเส้นขอบเริ่มแตกเป็นหลายเฉดโดยไม่มีลำดับชั้น
- **Recommendation:** เปลี่ยนเป็น OKLCH custom properties: `bg`, `surface`, `ink`, `muted`, `primary`, `accent`, `success`, `warning`, `danger`
- **Suggested command:** `$impeccable colorize USER_MANUAL.html`

### [P2] Typography ไม่มีบุคลิกและใช้หลายระบบโดยไม่มีเหตุผล

- **Location:** `USER_MANUAL.html:9`, `18`, `66`
- **Category:** Anti-Pattern / Accessibility
- **Impact:** Leelawadee UI ทำให้เอกสารดูเป็นค่า default ของ Windows ขณะที่ Consolas ทำให้ชื่อไฟล์ดูหลุดจากระบบไทยและอ่านเล็กเกินไป
- **Recommendation:** ใช้ font family ใหม่ตามหัวข้อ “Font Direction” ด้านล่าง พร้อม scale และ line-height สำหรับภาษาไทย
- **Suggested command:** `$impeccable typeset USER_MANUAL.html`

### [P2] Placeholder 26 จุดเป็นการ์ดซ้ำแบบ template

- **Location:** `USER_MANUAL.html:59-69` และ `.figure-slot` 26 จุด
- **Category:** Anti-Pattern
- **Impact:** ทุกภาพมีน้ำหนักเท่ากัน ทำให้ผู้ใช้ไม่รู้ว่าภาพใดสำคัญ และหน้าดูเหมือนถูกสร้างจาก component เดียวซ้ำ ๆ
- **Recommendation:** แบ่งเป็น hero frame, comparison pair, status strip และ troubleshooting evidence row; ใช้เลขเฉพาะ shot list สำหรับผู้จัดทำ ไม่ใช้เป็น visual badge สำหรับผู้อ่าน
- **Suggested command:** `$impeccable layout USER_MANUAL.html`

### [P2] ความยาวบรรทัดไม่มีเพดาน

- **Location:** `body`, `section`, paragraphs
- **Category:** Accessibility / Layout
- **Impact:** บนจอกว้างข้อความยาวเกิน 75 ตัวอักษรต่อบรรทัด ทำให้ไล่บรรทัดภาษาไทยยาก
- **Recommendation:** จำกัด prose ที่ 68–74ch และปล่อยตาราง/รูปกว้างเต็ม content rail แยกต่างหาก
- **Suggested command:** `$impeccable typeset USER_MANUAL.html`

### [P2] Author note ปรากฏในคู่มือผู้ใช้

- **Location:** `.editor-note` ในหน้าสารบัญ
- **Category:** Information Architecture
- **Impact:** คำสั่งสำหรับคนทำเอกสารรบกวนพนักงาน Packing และทำให้เอกสารดูยังไม่เสร็จ
- **Recommendation:** ซ่อนด้วย author mode หรือย้ายไป `images/README.md`
- **Suggested command:** `$impeccable distill USER_MANUAL.html`

### [P2] Print และ screen styles ไม่ได้แยกระบบกันจริง

- **Location:** `@page`, `.page`, `.cover`
- **Category:** Responsive Design
- **Impact:** ขนาด `pt`, `px`, `mm` ปะปน และ screen layout ต้องยอมตามข้อจำกัดกระดาษ
- **Recommendation:** ใช้ `rem/clamp()` บนจอ และกำหนด `pt/mm/page-break` เฉพาะใน `@media print`
- **Suggested command:** `$impeccable adapt USER_MANUAL.html`

### [P3] CSS เก่าที่ยังไม่ถูกใช้งาน

- **Location:** `.screen`, `.screen-title`, `.screen-row`, `.screen-cell`
- **Category:** Performance / Maintainability
- **Impact:** เพิ่มความสับสนในการแก้แบบครั้งถัดไป
- **Recommendation:** ลบ selectors ที่ไม่มี element ใช้งาน
- **Suggested command:** `$impeccable optimize USER_MANUAL.html`

### [P3] จังหวะภาพซ้ำทั้งเอกสาร

- **Location:** ตาราง, callout และ placeholder ทุก section
- **Category:** Anti-Pattern
- **Impact:** เนื้อหาทุกชนิดมีน้ำหนักใกล้กัน ทำให้เอกสารยาวแล้วเหนื่อยตา
- **Recommendation:** กำหนด section archetype ต่างกันตามงาน: preparation, process, comparison, status และ recovery
- **Suggested command:** `$impeccable bolder USER_MANUAL.html`

## Font Direction

คำสามคำสำหรับเสียงของงาน: **precise, mechanical, calm**

### ตัวเลือกที่เลือก

- **Heading: Chakra Petch 600/700**
  - รูปทรงสร้างจากเส้นตรงและมุม 45/90 องศา จึงให้ความรู้สึกคล้ายป้ายคำสั่งบนเครื่องจักร แต่ยังรองรับภาษาไทย
  - ใช้เฉพาะ H1–H3, step numbers และ navigation ไม่ใช้กับย่อหน้ายาว
- **Body: Bai Jamjuree 400/500/600**
  - Humanist Thai sans ที่อ่านย่อหน้ายาวได้ดีกว่า และมีน้ำหนักพอสำหรับหน้าจอกับงานพิมพ์
  - ใช้กับ body, table, callout และคำอธิบายภาพ

ทั้งสองตระกูลอยู่ใน Google Fonts และใช้ SIL Open Font License สามารถ self-host เพื่อให้คู่มือทำงาน offline ได้:

- https://github.com/google/fonts/tree/main/ofl/chakrapetch
- https://github.com/google/fonts/tree/main/ofl/baijamjuree

ค่าที่แนะนำ:

- Screen body: `clamp(1rem, 0.96rem + 0.2vw, 1.125rem)`, line-height `1.72`
- Print body: `11.5pt`, line-height `1.55`
- Heading weight: `600`; H1 ใช้ `700`
- หลีกเลี่ยง italic และตัวพิมพ์ใหญ่แบบ track กว้างในภาษาไทย

## Patterns & Systemic Issues

- Visual hierarchy ถูกสร้างด้วย “กล่อง + เส้น + สี” มากกว่าขนาดตัวอักษรและพื้นที่ว่าง
- Screen และ print ใช้ CSS ชุดเดียว ทำให้ไม่มีโหมดใดทำได้ดีเต็มที่
- Placeholder ถูกออกแบบเป็น component สำหรับระบบ แต่ไม่ได้จัดลำดับความสำคัญตามเรื่องเล่า
- ไม่มี token layer จึงเกิดเฉดสีน้ำเงิน/เทาแตกย่อยจำนวนมาก

## Positive Findings

- เนื้อหาครบและเรียงตาม workflow จริง
- ข้อความสถานะระบุเป็นคำ ไม่พึ่งสีอย่างเดียว
- Contrast ของ body 16.27:1 และ muted text 6.32:1 ผ่าน WCAG AA
- Static HTML เบาและเปิด offline ได้
- Grid ภาพมี breakpoint พื้นฐานที่ 760px

## Recommended Actions

1. **[P1] `$impeccable adapt USER_MANUAL.html`**: แยก screen/print layout และแก้ table/flow บน mobile
2. **[P1] `$impeccable harden USER_MANUAL.html`**: เพิ่ม landmarks, skip link, figure semantics และ table scopes
3. **[P2] `$impeccable typeset USER_MANUAL.html`**: ใช้ Chakra Petch + Bai Jamjuree และตั้ง Thai type scale ใหม่
4. **[P2] `$impeccable layout USER_MANUAL.html`**: เปลี่ยน A4-first document เป็น web-first manual shell และลด card repetition
5. **[P2] `$impeccable colorize USER_MANUAL.html`**: สร้าง OKLCH token system จาก teal seed และเลิกใช้ corporate navy/yellow
6. **[P3] `$impeccable polish USER_MANUAL.html`**: ตรวจ contrast, responsive, print และ visual rhythm รอบสุดท้าย

Re-run `$impeccable audit USER_MANUAL.html` หลังแก้เพื่อวัดคะแนนอีกครั้ง
