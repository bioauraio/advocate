#!/usr/bin/env node
/*
 * Компактный .docx БЕЗ бланка: только заголовок + плотный список.
 * Использование: node make_compact_doc.js <body.md> <output.docx> ["Заголовок"]
 * Markdown: # H1, ## H2, **жирный**, 1. нумерованные, - маркеры, --- черта.
 */
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, AlignmentType, HeadingLevel, BorderStyle,
} = require("docx");

function inlineRuns(text, base = {}) {
  const runs = [];
  const re = /(\*\*[^*]+\*\*)/g;
  let last = 0, m;
  const push = (t, extra) => { if (t !== "") runs.push(new TextRun({ text: t, ...base, ...extra })); };
  while ((m = re.exec(text)) !== null) {
    push(text.slice(last, m.index));
    push(m[0].slice(2, -2), { bold: true });
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
    let nm = line.match(/^(\d+)\.\s+(.*)$/);
    if (nm) {
      let parts = [nm[2]]; i++;
      while (i < lines.length && /^\s+\S/.test(lines[i]) && !/^\s*\d+\.\s/.test(lines[i])) { parts.push(lines[i].trim()); i++; }
      blocks.push({ type: "ol", num: nm[1], text: parts.join(" ") }); continue;
    }
    let bm = line.match(/^[-*]\s+(.*)$/);
    if (bm) { blocks.push({ type: "ul", text: bm[1] }); i++; continue; }
    const buf = [];
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === "" || /^(#{1,6})\s/.test(l) || /^---+\s*$/.test(l) || /^\d+\.\s/.test(l) || /^[-*]\s/.test(l)) break;
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
      out.push(new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "999999", space: 1 } }, spacing: { before: 40, after: 40 } }));
    } else if (b.type === "h") {
      out.push(new Paragraph({
        alignment: b.level === 1 ? AlignmentType.CENTER : AlignmentType.LEFT,
        spacing: { before: b.level === 1 ? 0 : 70, after: b.level === 1 ? 60 : 16 },
        children: inlineRuns(b.text, { bold: true, size: b.level === 1 ? 22 : 20 }),
      }));
    } else if (b.type === "ol") {
      out.push(new Paragraph({
        alignment: AlignmentType.JUSTIFIED, indent: { left: 340, hanging: 340 }, spacing: { after: 20, line: 216 },
        children: [new TextRun({ text: b.num + ". " }), ...inlineRuns(b.text)],
      }));
    } else if (b.type === "ul") {
      out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, bullet: { level: 0 }, spacing: { after: 30, line: 240 }, children: inlineRuns(b.text) }));
    } else {
      out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 40, line: 240 }, children: inlineRuns(b.text) }));
    }
  }
  return out;
}

function main() {
  const [bodyPath, outPath, title] = process.argv.slice(2);
  if (!bodyPath || !outPath) { console.error("args: <body.md> <output.docx> [title]"); process.exit(2); }
  const md = fs.readFileSync(bodyPath, "utf8");
  const children = [];
  if (title) children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [new TextRun({ text: title, bold: true, size: 24 })] }));
  children.push(...bodyParagraphs(parse(md)));

  const doc = new Document({
    styles: { default: { document: { run: { font: "Times New Roman", size: 20 } } } },
    sections: [{
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 567, right: 567, bottom: 567, left: 680 } } },
      children,
    }],
  });
  Packer.toBuffer(doc).then((b) => { fs.writeFileSync(outPath, b); console.log("OK:", outPath); });
}
main();
