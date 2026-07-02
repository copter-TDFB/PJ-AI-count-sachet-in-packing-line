const fs = require('fs');
const path = require('path');
const HTMLtoDOCX = require('C:/tmp/manual-docx/node_modules/html-to-docx');

async function main() {
  const root = __dirname;
  const htmlPath = path.join(root, 'USER_MANUAL.html');
  const docxPath = path.join(root, 'คู่มือการใช้งานระบบตรวจนับและพิมพ์ใบปะหน้า.docx');
  const html = fs.readFileSync(htmlPath, 'utf8');

  const buffer = await HTMLtoDOCX(html, null, {
    title: 'คู่มือการใช้งานระบบตรวจนับและพิมพ์ใบปะหน้า',
    subject: 'คู่มือสำหรับพนักงาน Packing',
    creator: 'PJ AI Count Sachet PK',
    keywords: ['Packing', 'AI', 'Sachet Counter', 'Auto Print'],
    description: 'คู่มือการใช้งานระบบ AI ตรวจนับซองและพิมพ์ใบปะหน้าอัตโนมัติ',
    font: 'Leelawadee UI',
    fontSize: 28,
    pageNumber: true,
    margins: {
      top: 907,
      right: 907,
      bottom: 964,
      left: 907,
      header: 360,
      footer: 360,
      gutter: 0,
    },
  });

  fs.writeFileSync(docxPath, buffer);
  const size = fs.statSync(docxPath).size;
  process.stdout.write(`${docxPath}\n${size} bytes\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
