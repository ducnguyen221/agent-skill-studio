// Markdown → HTML tối giản cho trang Docs, không phụ thuộc npm (site tĩnh, chạy được ở mọi repo).
// Hỗ trợ: front matter (bỏ), tiêu đề, đoạn, **đậm**, *nghiêng*, `mã`, khối ``` , trích dẫn, danh sách (lồng theo thụt),
// bảng ống, đường kẻ, link, ảnh, <url>. HTML thô trong .md bị thoát (tài liệu là dữ liệu, không chạy).
// rewriteHref(href) cho phép trang Docs đổi link giữa các .md sang trang đã dựng.

export const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const SAFE_URL = /^(https?:|mailto:|#|\.{0,2}\/|[A-Za-z0-9_.~-])/;

function inline(text, rewriteHref) {
  const slots = [];
  const keep = (html) => `\u0000${slots.push(html) - 1}\u0000`;
  let s = text.replace(/`([^`]+)`/g, (_, c) => keep(`<code>${esc(c)}</code>`));
  const href = (u) => {
    const raw = u.trim().replace(/^<|>$/g, '');
    if (!SAFE_URL.test(raw) || /^javascript:/i.test(raw)) return null;
    return rewriteHref ? rewriteHref(raw) : raw;
  };
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_, alt, u) => {
    const h = href(u);
    return h ? keep(`<img src="${esc(h)}" alt="${esc(alt)}">`) : keep(esc(alt));
  });
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_, label, u) => {
    const h = href(u);
    const inner = inline(label, null);
    return h ? keep(`<a href="${esc(h)}">${inner}</a>`) : keep(inner);
  });
  s = s.replace(/<(https?:\/\/[^>\s]+)>/g, (_, u) => keep(`<a href="${esc(u)}">${esc(u)}</a>`));
  s = esc(s);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_]+)__/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>').replace(/(^|[^_\w])_([^_\s][^_]*)_(?!\w)/g, '$1<em>$2</em>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[Number(i)]);
}

const splitRow = (line) => line.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));
const isTableSep = (line) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line);
const listItem = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

function renderList(lines, start, rewriteHref) {
  const first = listItem.exec(lines[start]);
  const indent = first[1].length;
  const ordered = /\d/.test(first[2]);
  let i = start;
  const items = [];
  while (i < lines.length) {
    const m = listItem.exec(lines[i]);
    if (m && m[1].length === indent) { items.push([m[3]]); i++; continue; }
    if (m && m[1].length > indent) {
      const sub = renderList(lines, i, rewriteHref);
      items[items.length - 1].push(sub.html); i = sub.next; continue;
    }
    if (!m && lines[i].trim() && /^\s+/.test(lines[i]) && items.length) { items[items.length - 1][0] += ' ' + lines[i].trim(); i++; continue; }
    break;
  }
  const tag = ordered ? 'ol' : 'ul';
  const html = `<${tag}>${items.map(([t, ...subs]) => `<li>${inline(t, rewriteHref)}${subs.join('')}</li>`).join('')}</${tag}>`;
  return { html, next: i };
}

/** Trả về { html, title } — title là tiêu đề # đầu tiên (nếu có). */
export function renderMarkdown(src, rewriteHref) {
  let text = src.replace(/\r\n?/g, '\n');
  if (text.startsWith('---\n')) {
    const end = text.indexOf('\n---', 4);
    if (end > 0) text = text.slice(text.indexOf('\n', end + 1) + 1);
  }
  const lines = text.split('\n');
  const out = [];
  let title = null;
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const fence = /^\s*(```+|~~~+)\s*([\w+-]*)/.exec(line);
    if (fence) {
      const body = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++]);
      i++;
      out.push(`<pre><code${fence[2] ? ` class="language-${esc(fence[2])}"` : ''}>${esc(body.join('\n'))}</code></pre>`);
      continue;
    }
    const h = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (h) {
      const level = h[1].length;
      if (level === 1 && title === null) title = h[2].replace(/[`*_]/g, '');
      out.push(`<h${level}>${inline(h[2], rewriteHref)}</h${level}>`);
      i++; continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
    if (/^\s*>/.test(line)) {
      const body = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ''));
      out.push(`<blockquote>${renderMarkdown(body.join('\n'), rewriteHref).html}</blockquote>`);
      continue;
    }
    if (line.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(splitRow(lines[i++]));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inline(c, rewriteHref)}</th>`).join('')}</tr></thead><tbody>${
        rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c, rewriteHref)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    if (listItem.test(line)) {
      const r = renderList(lines, i, rewriteHref);
      out.push(r.html); i = r.next; continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*(```|~~~)|\s*>)/.test(lines[i]) && !listItem.test(lines[i])
      && !(lines[i].includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1]))) para.push(lines[i++].trim());
    out.push(`<p>${inline(para.join(' '), rewriteHref)}</p>`);
  }
  return { html: out.join('\n'), title };
}
