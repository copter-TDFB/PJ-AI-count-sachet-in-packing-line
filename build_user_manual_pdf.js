const fs = require('fs');
const path = require('path');
const PDFDocument = require('C:/tmp/manual-docx/node_modules/pdfkit');
const cheerio = require('C:/tmp/manual-docx/node_modules/cheerio');

const root = __dirname;
const htmlPath = path.join(root, 'USER_MANUAL.html');
const pdfPath = path.join(root, 'คู่มือการใช้งานระบบตรวจนับและพิมพ์ใบปะหน้า.pdf');
const $ = cheerio.load(fs.readFileSync(htmlPath, 'utf8'));

const doc = new PDFDocument({ size: 'A4', margins: { top: 46, right: 46, bottom: 52, left: 46 }, bufferPages: true, info: {
  Title: 'คู่มือการใช้งานระบบตรวจนับและพิมพ์ใบปะหน้า',
  Author: 'PJ AI Count Sachet PK',
  Subject: 'คู่มือสำหรับพนักงาน Packing',
} });
const output = fs.createWriteStream(pdfPath);
doc.pipe(output);
doc.registerFont('Thai', 'C:/Windows/Fonts/LeelawUI.ttf');
doc.registerFont('ThaiBold', 'C:/Windows/Fonts/LeelaUIb.ttf');

const ink = '#172033';
const blue = '#123a63';
const midBlue = '#1d5f9f';
const green = '#176b32';
const orange = '#9a5200';
const red = '#a61b15';
const contentWidth = doc.page.width - doc.page.margins.left - doc.page.margins.right;

function clean(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function ensureSpace(height) {
  const bottom = doc.page.height - doc.page.margins.bottom;
  if (doc.y + height > bottom) doc.addPage();
}

function heading(text, level = 2) {
  doc.x = doc.page.margins.left;
  const size = level === 2 ? 20 : 15;
  ensureSpace(level === 2 ? 54 : 36);
  doc.font('ThaiBold').fontSize(size).fillColor(blue).text(text, { lineGap: 2 });
  if (level === 2) {
    doc.moveDown(0.18);
    doc.strokeColor(midBlue).lineWidth(1.5).moveTo(doc.page.margins.left, doc.y).lineTo(doc.page.width - doc.page.margins.right, doc.y).stroke();
  }
  doc.moveDown(0.45);
}

function paragraph(text, options = {}) {
  if (!text) return;
  doc.x = doc.page.margins.left;
  doc.font(options.bold ? 'ThaiBold' : 'Thai').fontSize(options.size || 12.5).fillColor(options.color || ink)
    .text(text, { lineGap: 3, align: options.align || 'left' });
  doc.moveDown(options.after ?? 0.45);
}

function list($node, ordered) {
  const items = $node.children('li').toArray().map((li) => clean($(li).text()));
  items.forEach((text, index) => {
    ensureSpace(34);
    const marker = ordered ? `${index + 1}.` : '•';
    const x = doc.page.margins.left;
    const y = doc.y;
    doc.font('Thai').fontSize(12.5);
    const itemHeight = doc.heightOfString(text, { width: contentWidth - 25, lineGap: 3 });
    doc.font('ThaiBold').fontSize(12.5).fillColor(blue).text(marker, x, y, { width: 25 });
    doc.font('Thai').fontSize(12.5).fillColor(ink).text(text, x + 25, y, { width: contentWidth - 25, lineGap: 3 });
    doc.x = doc.page.margins.left;
    doc.y = y + itemHeight + 7;
  });
  doc.x = doc.page.margins.left;
  doc.moveDown(0.2);
}

function callout($node) {
  const classes = $node.attr('class') || '';
  let bg = '#e8f1fb'; let border = midBlue;
  if (classes.includes('warn')) { bg = '#fff4d6'; border = orange; }
  if (classes.includes('danger')) { bg = '#fdeaea'; border = red; }
  if (classes.includes('success')) { bg = '#e8f6ed'; border = green; }
  const title = clean($node.find('strong').first().text());
  const clone = $node.clone();
  clone.find('strong').first().remove();
  const body = clean(clone.text());
  doc.font('ThaiBold').fontSize(13).fillColor(border);
  const titleH = doc.heightOfString(title, { width: contentWidth - 28 });
  doc.font('Thai').fontSize(12.3);
  const bodyH = doc.heightOfString(body, { width: contentWidth - 28, lineGap: 3 });
  const h = titleH + bodyH + 27;
  ensureSpace(h + 12);
  const x = doc.page.margins.left; const y = doc.y;
  doc.save().fillColor(bg).strokeColor(border).lineWidth(1.5).rect(x, y, contentWidth, h).fillAndStroke().restore();
  doc.font('ThaiBold').fontSize(13).fillColor(border).text(title, x + 14, y + 10, { width: contentWidth - 28 });
  doc.font('Thai').fontSize(12.3).fillColor(ink).text(body, x + 14, y + 11 + titleH, { width: contentWidth - 28, lineGap: 3 });
  doc.y = y + h + 12;
}

function flowTable($table) {
  const cells = $table.find('tr').first().children('td').toArray();
  ensureSpace(72);
  const labels = cells.filter((_, i) => i % 2 === 0).map((c) => clean($(c).text()));
  const gap = 18; const boxW = (contentWidth - gap * (labels.length - 1)) / labels.length;
  const y = doc.y;
  labels.forEach((label, i) => {
    const x = doc.page.margins.left + i * (boxW + gap);
    doc.save().fillColor('#e8f1fb').strokeColor(midBlue).lineWidth(1.4).rect(x, y, boxW, 54).fillAndStroke().restore();
    doc.font('ThaiBold').fontSize(12.5).fillColor(blue).text(label, x + 5, y + 11, { width: boxW - 10, align: 'center' });
    if (i < labels.length - 1) doc.font('ThaiBold').fontSize(18).fillColor(midBlue).text('>', x + boxW, y + 13, { width: gap, align: 'center' });
  });
  doc.y = y + 68;
  doc.x = doc.page.margins.left;
}

function table($table) {
  if ($table.hasClass('flow')) return flowTable($table);
  const rows = $table.find('tr').toArray();
  if (!rows.length) return;
  const columnCount = Math.max(...rows.map((row) => $(row).children('th,td').length));
  const widths = Array(columnCount).fill(contentWidth / columnCount);
  const pad = 6;

  rows.forEach((row, rowIndex) => {
    const cells = $(row).children('th,td').toArray();
    const isHeader = rowIndex === 0 && $(row).children('th').length > 0;
    doc.font(isHeader ? 'ThaiBold' : 'Thai').fontSize(10.8);
    let rowHeight = 26;
    cells.forEach((cell, i) => {
      rowHeight = Math.max(rowHeight, doc.heightOfString(clean($(cell).text()), { width: widths[i] - pad * 2, lineGap: 2 }) + pad * 2);
    });
    ensureSpace(rowHeight + 2);
    const y = doc.y;
    let x = doc.page.margins.left;
    cells.forEach((cell, i) => {
      doc.save().fillColor(isHeader ? blue : (rowIndex % 2 ? '#ffffff' : '#f5f8fb')).strokeColor('#b9c4d0').lineWidth(0.7)
        .rect(x, y, widths[i], rowHeight).fillAndStroke().restore();
      doc.font(isHeader ? 'ThaiBold' : 'Thai').fontSize(10.8).fillColor(isHeader ? '#ffffff' : ink)
        .text(clean($(cell).text()), x + pad, y + pad, { width: widths[i] - pad * 2, lineGap: 2 });
      x += widths[i];
    });
    doc.y = y + rowHeight;
  });
  doc.x = doc.page.margins.left;
  doc.moveDown(0.7);
}

function step($node) {
  const no = clean($node.find('.step-no').text());
  const title = clean($node.find('.step-body strong').text());
  const clone = $node.find('.step-body').clone();
  clone.find('strong').remove();
  const body = clean(clone.text());
  ensureSpace(60);
  const x = doc.page.margins.left; const y = doc.y;
  doc.save().fillColor(blue).rect(x, y, 38, 38).fill().restore();
  doc.font('ThaiBold').fontSize(17).fillColor('#fff').text(no, x, y + 7, { width: 38, align: 'center' });
  doc.font('ThaiBold').fontSize(13.5).fillColor(blue).text(title, x + 49, y, { width: contentWidth - 49 });
  doc.font('Thai').fontSize(12).fillColor(ink).text(body, x + 49, doc.y + 1, { width: contentWidth - 49, lineGap: 2.5 });
  doc.moveDown(0.55);
}

function screen($node) {
  const title = clean($node.find('.screen-title').text()) || 'ภาพอธิบาย';
  const labels = $node.find('.screen-cell').toArray().map((cell) => clean($(cell).text()));
  const caption = clean($node.find('.screen-caption').text());
  const h = labels.length ? 104 : 66;
  ensureSpace(h + 25);
  const x = doc.page.margins.left; const y = doc.y;
  doc.save().fillColor('#f3f6f9').strokeColor('#8493a5').lineWidth(1.2).rect(x, y, contentWidth, h).fillAndStroke().restore();
  doc.save().fillColor(blue).rect(x, y, contentWidth, 24).fill().restore();
  doc.font('ThaiBold').fontSize(10.5).fillColor('#fff').text(title, x + 8, y + 5, { width: contentWidth - 16 });
  if (labels.length) {
    const gap = 6; const w = (contentWidth - 16 - gap * (labels.length - 1)) / labels.length;
    labels.forEach((label, i) => {
      const cx = x + 8 + i * (w + gap);
      doc.save().fillColor('#fff').strokeColor('#b5c0cb').rect(cx, y + 32, w, 52).fillAndStroke().restore();
      doc.font('ThaiBold').fontSize(10.2).fillColor(blue).text(label, cx + 4, y + 42, { width: w - 8, align: 'center' });
    });
  }
  doc.y = y + h + 5;
  if (caption) paragraph(caption, { size: 9.5, color: '#526174', after: 0.5 });
}

function renderSection($section, index) {
  if (index > 0) doc.addPage();
  $section.children().each((_, el) => {
    const $el = $(el);
    const tag = el.tagName?.toLowerCase();
    if (tag === 'h2') heading(clean($el.text()), 2);
    else if (tag === 'h3') heading(clean($el.text()), 3);
    else if (tag === 'p') paragraph(clean($el.text()), { size: $el.hasClass('footer-note') ? 10.5 : 12.5, color: $el.hasClass('footer-note') ? '#526174' : ink });
    else if (tag === 'ul') list($el, false);
    else if (tag === 'ol') list($el, true);
    else if (tag === 'table') table($el);
    else if ($el.hasClass('callout')) callout($el);
    else if ($el.hasClass('step')) step($el);
    else if ($el.hasClass('screen')) screen($el);
  });
}

// Cover
doc.save().fillColor(blue).rect(0, 0, doc.page.width, 18).fill().restore();
doc.y = 150;
paragraph('สำหรับพนักงาน Packing', { bold: true, size: 15, color: midBlue, after: 0.7 });
doc.font('ThaiBold').fontSize(27).fillColor(blue).text('คู่มือการใช้งานระบบ\nAI ตรวจนับซองและพิมพ์ใบปะหน้าอัตโนมัติ', { lineGap: 5 });
doc.moveDown(0.8);
paragraph('ครอบคลุมการเปิดระบบ การสแกนใบ Pack การวางซองให้ AI ตรวจนับ การพิมพ์ใบปะหน้า และการแก้ปัญหาเบื้องต้น', { size: 15, color: '#46566a', after: 1.2 });
doc.save().fillColor('#e8f1fb').strokeColor(midBlue).lineWidth(1.4).rect(doc.page.margins.left, doc.y, 255, 45).fillAndStroke().restore();
doc.font('ThaiBold').fontSize(13.5).fillColor(blue).text('อ่าน Checklist ก่อนเริ่มงานทุกครั้ง', doc.page.margins.left + 12, doc.y + 12, { width: 230 });
doc.save().fillColor('#f4b400').rect(0, doc.page.height - 12, doc.page.width, 12).fill().restore();

$('section.page').each((index, section) => renderSection($(section), index + 1));

// Page numbers
const range = doc.bufferedPageRange();
for (let i = range.start; i < range.start + range.count; i += 1) {
  doc.switchToPage(i);
  if (i === 0) continue;
  const originalBottomMargin = doc.page.margins.bottom;
  doc.page.margins.bottom = 0;
  doc.font('Thai').fontSize(9).fillColor('#667487').text(`หน้า ${i + 1} จาก ${range.count}`,
    doc.page.margins.left, doc.page.height - 28, { width: contentWidth, align: 'center', lineBreak: false });
  doc.page.margins.bottom = originalBottomMargin;
}

doc.end();
output.on('finish', () => {
  process.stdout.write(`${pdfPath}\n${fs.statSync(pdfPath).size} bytes\n`);
});
