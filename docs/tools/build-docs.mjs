#!/usr/bin/env node
// Dựng trang Docs của một site: mọi *.md có trong git dưới <root> → <root>/docs/<đường không .md>/index.html,
// thêm trang danh sách <root>/docs/index.html và sổ <root>/docs/docs-index.json (sha256 từng nguồn).
// Dựng sẵn lúc build vì file:// chặn tải .md. Không mạng, không npm.
// Dùng: node build-docs.mjs [--root docs] [--check]   (--check: không ghi, exit 1 nếu trang Docs đã cũ)
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, posix, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { renderMarkdown, esc } from './md.mjs';
import { DEFAULT_CONFIG, page } from './shell.mjs';

export const OUT = 'docs';
const lf = (s) => s.replace(/\r\n?/g, '\n');
const sha256 = (t) => createHash('sha256').update(lf(t), 'utf8').digest('hex');

export function loadConfig(root) {
  const p = join(root, 'assets', 'ds', 'site.json');
  const cfg = existsSync(p) ? { ...DEFAULT_CONFIG, ...JSON.parse(readFileSync(p, 'utf8')) } : { ...DEFAULT_CONFIG };
  const lock = join(root, 'assets', 'ds', 'ds-lock.json');
  cfg.dsVersion = existsSync(lock) ? JSON.parse(readFileSync(lock, 'utf8')).version : undefined;
  return cfg;
}

/** Danh sách .md đã có trong git dưới root (đường tương đối, dấu /), trừ thư mục Docs sinh ra. */
export function trackedMarkdown(root, cfg = {}) {
  const base = sourceRoot(root, cfg);
  const raw = execFileSync('git', ['-C', base, 'ls-files', '-z', '--', '*.md', '*.MD'], { encoding: 'utf8' });
  let list = raw.split('\0').filter(Boolean).filter((p) => !p.startsWith(`${OUT}/`));
  // Tuỳ chọn của repo này: nguồn .md nằm ngoài docs/ (site.json: docsSource, docsInclude).
  if (Array.isArray(cfg.docsInclude)) list = list.filter((p) => cfg.docsInclude.includes(p));
  return list.sort();
}

/** Thư mục chứa nguồn .md: mặc định chính root; site.json `docsSource` (đường tương đối từ root) đổi sang thư mục khác. */
export function sourceRoot(root, cfg = {}) {
  return cfg.docsSource ? resolve(root, cfg.docsSource) : root;
}

function repoPrefix(root) {
  return execFileSync('git', ['-C', root, 'rev-parse', '--show-prefix'], { encoding: 'utf8' }).trim();
}

const pageOf = (src) => `${OUT}/${src.replace(/\.md$/i, '')}/index.html`;
const relUp = (path) => '../'.repeat(path.split('/').length - 1);

function groupByDir(list) {
  const groups = new Map();
  for (const d of list) {
    const dir = posix.dirname(d.src) === '.' ? '' : posix.dirname(d.src) + '/';
    if (!groups.has(dir)) groups.set(dir, []);
    groups.get(dir).push(d);
  }
  return groups;
}

function toc(list, here, rel) {
  let html = '  <nav class="doc-toc" aria-label="Tài liệu">\n    <b>Tài liệu</b>\n';
  for (const [dir, items] of groupByDir(list)) {
    if (dir) html += `    <p class="dir">${esc(dir)}</p>\n`;
    html += '    <ul>\n' + items.map((d) => d.src === here
      ? `      <li><a href="${rel}${d.out}" aria-current="page">${esc(d.title)}</a></li>`
      : `      <li><a href="${rel}${d.out}">${esc(d.title)}</a></li>`).join('\n') + '\n    </ul>\n';
  }
  return html + '  </nav>';
}

export function render(root) {
  const cfg = loadConfig(root);
  const base = sourceRoot(root, cfg);
  const srcs = trackedMarkdown(root, cfg);
  const prefix = repoPrefix(base);
  const docs = srcs.map((src) => {
    const text = lf(readFileSync(join(base, src), 'utf8'));
    const title = renderMarkdown(text).title || posix.basename(src, '.md');
    return { src, out: pageOf(src), title, sha256: sha256(text), text };
  });
  const bySrc = new Map(docs.map((d) => [d.src, d]));
  const files = {};
  const indexPath = `${OUT}/index.html`;

  for (const d of docs) {
    const rel = relUp(d.out);
    const rewrite = (href) => {
      if (/^[a-z]+:/i.test(href) || href.startsWith('#')) return href;
      const [p, frag = ''] = href.split('#');
      const target = posix.normalize(posix.join(posix.dirname(d.src), p));
      const hash = frag ? `#${frag}` : '';
      if (bySrc.has(target)) return `${rel}${bySrc.get(target).out}${hash}`;
      if (!cfg.docsSource && !target.startsWith('../') && existsSync(join(base, target))) return `${rel}${target}${hash}`;
      const inRepo = posix.normalize(prefix + target);
      return inRepo.startsWith('../') ? '#' : `${cfg.repo}/blob/main/${inRepo}${hash}`;
    };
    const body = renderMarkdown(d.text, rewrite).html;
    const main = `<div class="wrap"><div class="doc-layout">
${toc(docs, d.src, rel)}
  <article class="prose">
    <div class="doc-meta"><a href="${rel}${indexPath}">Docs</a> / <code>${esc(d.src)}</code></div>
${body.startsWith('<h1>') ? body : `<h1>${esc(d.title)}</h1>\n${body}`}
  </article>
</div></div>`;
    files[d.out] = page({ cfg, rel, path: d.out, active: indexPath, title: `${d.title} · Docs · ${cfg.name}`,
      description: `Tài liệu ${d.src} của ${cfg.name}.`, main, version: cfg.dsVersion });
  }

  let list = '';
  for (const [dir, items] of groupByDir(docs)) {
    list += `    <h2 class="dir-h" style="font-size:1.05rem;margin:28px 0 12px">${esc(dir || 'Gốc')}</h2>\n    <div class="doc-list">\n`
      + items.map((d) => `      <a href="../${d.out}"><b>${esc(d.title)}</b><span>${esc(d.src)}</span></a>`).join('\n') + '\n    </div>\n';
  }
  const empty = docs.length ? '' : '    <p class="note">Chưa có tài liệu Markdown nào trong git.</p>\n';
  files[indexPath] = page({ cfg, rel: '../', path: indexPath, active: indexPath, title: `Docs · ${cfg.name}`,
    description: `Mọi tài liệu Markdown của ${cfg.name}, dựng thành trang dễ đọc.`, version: cfg.dsVersion,
    main: `<section class="page-hero"><div class="wrap">
  <span class="eyebrow">Docs</span>
  <h1>Tài liệu</h1>
  <p class="lead">${docs.length} tài liệu Markdown có trong repo, dựng thành trang đọc được cả khi mở bằng file://.</p>
</div></section>
<section style="padding-top:8px"><div class="wrap">
${empty}${list}</div></section>` });

  files[`${OUT}/docs-index.json`] = JSON.stringify({
    generator: 'opcos-site-kit/build-docs', version: 1,
    docs: docs.map(({ src, out, title, sha256: h }) => ({ src, out, title, sha256: h })),
  }, null, 2) + '\n';
  return files;
}

/** Trang Docs cũ: file thiếu, khác nội dung, hoặc trang thừa trong <root>/docs/ không còn nguồn. */
export function staleFiles(root) {
  const files = render(root);
  const stale = [];
  for (const [rel, text] of Object.entries(files)) {
    const p = join(root, rel);
    if (!existsSync(p) || lf(readFileSync(p, 'utf8')) !== text) stale.push(rel);
  }
  const outDir = join(root, OUT);
  if (existsSync(outDir)) {
    const walk = (d, base) => {
      for (const e of readdirSync(d, { withFileTypes: true })) {
        const r = `${base}/${e.name}`;
        if (e.isDirectory()) walk(join(d, e.name), r);
        else if (!(r in files) && /\.(html|json)$/.test(e.name)) stale.push(`${r} (thừa)`);
      }
    };
    walk(outDir, OUT);
  }
  return { files, stale };
}

function main() {
  const args = process.argv.slice(2);
  const i = args.indexOf('--root');
  const root = resolve(i >= 0 ? args[i + 1] : 'docs');
  if (args.includes('--check')) {
    const { stale } = staleFiles(root);
    for (const s of stale) console.error(`stale: ${s}`);
    if (stale.length) { console.error('build-docs: trang Docs đã cũ — chạy lại build-docs.mjs'); process.exit(1); }
    console.log('build-docs: fresh');
    return;
  }
  const files = render(root);
  for (const [rel, text] of Object.entries(files)) {
    const p = join(root, rel);
    mkdirSync(dirname(p), { recursive: true });
    if (!existsSync(p) || lf(readFileSync(p, 'utf8')) !== text) { writeFileSync(p, text, 'utf8'); console.log(`wrote ${rel}`); }
  }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) main();
