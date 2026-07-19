#!/usr/bin/env node
/*
 * Собирает .docx на бланке адвоката/адвокатского образования:
 *   шапка (логотип + реквизиты) сверху, затем тело из markdown-файла.
 *
 * Использование:
 *   node make_letterhead_doc.js <body.md> <output.docx> ["Заголовок (необязательно)"]
 *
 * <body.md>  — файл с текстом документа в markdown (# заголовки, **жирный**,
 *              списки 1. / -, цитаты >, --- горизонтальная черта).
 * Логотип берётся из ../assets/letterhead_logo.png относительно скрипта.
 * Реквизиты шапки — из ./letterhead.json (см. letterhead.example.json).
 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, AlignmentType,
  HeadingLevel, BorderStyle,
} = require("docx");

const SCRIPT_DIR = __dirname;
const LOGO = path.join(SCRIPT_DIR, "..", "assets", "letterhead_logo.png");

// --- реквизиты (постоянная шапка) из letterhead.json ---
// Формат: {"lines": [{"t": "ТЕКСТ СТРОКИ", "bold": true}, ...]}
const FIRM_CONFIG = path.join(SCRIPT_DIR, "letterhead.json");
if (!fs.existsSync(FIRM_CONFIG)) {
  console.error(
    "Нет tools/letterhead.json с реквизитами бланка.\n" +
    "Скопируй letterhead.example.json в letterhead.json и впиши свои реквизиты."
  );
  process.exit(1);
}
const FIRM = JSON.parse(fs.readFileSync(FIRM_CONFIG, "utf8")).lines;

function inlineRuns(text, base = {}) {
  const runs = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  const push = (t, extra) => { if (t !== "") runs.push(new TextRun({ text: t, ...base, ...extra })); };
  while ((m = re.exec(text)) !== null) {
    push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) push(tok.slice(2, -2), { bold: true });
    else push(tok.slice(1, -1), { font: "Courier New", size: 22 });
    last = re.lastIndex;
  }
  push(text.slice(last));
  if (runs.length === 0) runs.push(new TextRun({ text: "", ...base }));
  return runs;
}

function parse(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    let line = lines[i];
    if (line.trim() === "") { i++; continue; }
    if (/^---+\s*$/.test(line)) { blocks.push({ type: "hr" }); i++; continue; }
    let h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { blocks.push({ type: "h", level: h[1].length, text: h[2].trim() }); i++; continue; }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, "").trim()); i++; }
      blocks.push({ type: "quote", text: buf.join(" ") }); continue;
    }
    let nm = line.match(/^(\d+)\.\s+(.*)$/);
    if (nm) {
      let parts = [nm[2]]; i++;
      while (i < lines.length && /^\s+\S/.test(lines[i]) && !/^\s*\d+\.\s/.test(lines[i])) { parts.push(lines[i].trim()); i++; }
      blocks.push({ type: "ol", num: nm[1], text: parts.join(" ") }); continue;
    }
    let bm = line.match(/^[-*]\s+(.*)$/);
    if (bm) {
      let parts = [bm[1]]; i++;
      while (i < lines.length && /^\s+\S/.test(lines[i]) && !/^[-*]\s/.test(lines[i])) { parts.push(lines[i].trim()); i++; }
      blocks.push({ type: "ul", text: parts.join(" ") }); continue;
    }
    const buf = [];
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === "" || /^(#{1,6})\s/.test(l) || /^---+\s*$/.test(l) || /^>\s?/.test(l) || /^\d+\.\s/.test(l) || /^[-*]\s/.test(l)) break;
      buf.push(l.trim()); i++;
    }
    blocks.push({ type: "p", text: buf.join(" ") });
  }
  return blocks;
}

function bodyParagraphs(blocks) {
  const out = [];
  for (const b of blocks) {
    if (b.type === "hr") {
      out.push(new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "999999", space: 1 } }, spacing: { before: 120, after: 120 } }));
    } else if (b.type === "h") {
      const lvl = b.level === 1 ? HeadingLevel.HEADING_1 : b.level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3;
      out.push(new Paragraph({ heading: lvl, alignment: b.level === 1 ? AlignmentType.CENTER : AlignmentType.LEFT, children: inlineRuns(b.text, { bold: true }) }));
    } else if (b.type === "quote") {
      out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, indent: { left: 567 }, spacing: { after: 60 }, children: inlineRuns(b.text, { italics: true, color: "555555" }) }));
    } else if (b.type === "ol") {
      out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, indent: { left: 720, hanging: 420 }, spacing: { after: 60 }, children: [new TextRun({ text: b.num + ". " }), ...inlineRuns(b.text)] }));
    } else if (b.type === "ul") {
      out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, bullet: { level: 0 }, spacing: { after: 40 }, children: inlineRuns(b.text) }));
    } else {
      out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 120 }, children: inlineRuns(b.text) }));
    }
  }
  return out;
}

function letterhead() {
  const paras = [];
  // логотип по центру (масштаб по ширине ≤ 480px)
  try {
    const buf = fs.readFileSync(LOGO);
    let w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
    const maxW = 480;
    if (w > maxW) { const s = maxW / w; w = Math.round(w * s); h = Math.round(h * s); }
    paras.push(new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { after: 80 },
      children: [new ImageRun({ type: "png", data: buf, transformation: { width: w, height: h },
        altText: { title: "logo", description: "Логотип адвокатского кабинета", name: "logo" } })],
    }));
  } catch (e) { /* нет логотипа — пропускаем картинку, шапка останется текстовой */ }
  for (const l of FIRM) {
    paras.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 20 },
      children: [new TextRun({ text: l.t, bold: l.bold, size: l.bold ? 24 : 22 })] }));
  }
  paras.push(new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: "333333", space: 1 } }, spacing: { before: 60, after: 200 } }));
  return paras;
}

function main() {
  const [bodyPath, outPath, title] = process.argv.slice(2);
  if (!bodyPath || !outPath) {
    console.error("Использование: node make_letterhead_doc.js <body.md> <output.docx> [\"Заголовок\"]");
    process.exit(2);
  }
  const md = fs.readFileSync(bodyPath, "utf8");
  const children = [...letterhead()];
  if (title) children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, alignment: AlignmentType.CENTER, children: [new TextRun({ text: title, bold: true })] }));
  children.push(...bodyParagraphs(parse(md)));

  const doc = new Document({
    styles: {
      default: { document: { run: { font: "Times New Roman", size: 28 } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 30, bold: true, font: "Times New Roman" }, paragraph: { spacing: { before: 240, after: 200 }, outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, bold: true, font: "Times New Roman" }, paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 1 } },
        { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, bold: true, font: "Times New Roman" }, paragraph: { spacing: { before: 160, after: 100 }, outlineLevel: 2 } },
      ],
    },
    sections: [{
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, right: 851, bottom: 1134, left: 1701 } } },
      children,
    }],
  });
  Packer.toBuffer(doc).then((b) => { fs.writeFileSync(outPath, b); console.log("OK:", outPath); });
}

main();
