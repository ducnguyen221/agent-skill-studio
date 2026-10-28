#!/usr/bin/env node
// Kiểm một site tĩnh dựng trên OpcOS Design System. Không mạng, không npm.
//   1. docs/assets/ds/: site.css, site.js khớp sha256 trong ds-lock.json (bản chép không bị sửa tay)
//   2. --source <kit/assets>: ds-lock.json trùng bản phát hành của xưởng (bản chép không cũ)
//   3. menu: mọi trang trong site.json có mặt; header đủ mục, đúng thứ tự, đúng một aria-current="page"; footer lặp lại menu
//   4. link nội bộ: mọi href/src trỏ tới file có thật; cấm link tới thư mục trần (file:// không mở được)
//   5. Docs: trang dựng từ .md còn tươi (build-docs --check)
// Dùng: node check-site.mjs [--root docs] [--source <đường tới kit/assets>]
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join, posix, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { loadConfig, staleFiles, OUT } from './build-docs.mjs';

const lf = (s) => s.replace(/\r\n?/g, '\n');
const sha256 = (t) => createHash('sha256').update(lf(t), 'utf8').digest('hex');
const decode = (s) => s.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'");

function htmlFiles(root) {
  const out = [];
  const walk = (dir, base) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.name.startsWith('.') || e.name === 'node_modules') continue;
      const rel = base ? `${base}/${e.name}` : e.name;
      if (e.isDirectory()) { if (rel !== 'assets') walk(join(dir, e.name), rel); }
      else if (e.name.endsWith('.html')) out.push(rel);
    }
  };
  walk(root, '');
  return out.sort();
}

const links = (html) => [...html.matchAll(/<a\b([^>]*)>/g)].map((m) => {
  const href = /\bhref="([^"]*)"/.exec(m[1]);
  return { href: href ? decode(href[1]) : null, current: /\baria-current="page"/.test(m[1]) };
});
const region = (html, re) => { const m = re.exec(html); return m ? m[0] : null; };

export function checkSite(root, { source } = {}) {
  const errors = [];
  const ds = join(root, 'assets', 'ds');
  // 1 + 2: bản chép DS
  const lockPath = join(ds, 'ds-lock.json');
  if (!existsSync(lockPath)) errors.push('assets/ds/ds-lock.json: thiếu — chạy install.mjs của xưởng');
  else {
    const lock = JSON.parse(readFileSync(lockPath, 'utf8'));
    for (const [name, hash] of Object.entries(lock.files)) {
      const p = join(ds, name);
      if (!existsSync(p)) errors.push(`assets/ds/${name}: thiếu`);
      else if (sha256(readFileSync(p, 'utf8')) !== hash) errors.push(`assets/ds/${name}: khác bản phát hành ${lock.version} (bị sửa tay?) — chép lại bằng install.mjs`);
    }
    if (source) {
      const src = JSON.parse(readFileSync(join(source, 'ds-lock.json'), 'utf8'));
      if (src.version !== lock.version || JSON.stringify(src.files) !== JSON.stringify(lock.files)) {
        errors.push(`assets/ds/ds-lock.json: bản chép ${lock.version} lệch bản của xưởng ${src.version} — chạy install.mjs`);
      }
    }
  }
  // 3: menu
  const cfg = loadConfig(root);
  const menu = cfg.menu.map((m) => m.href);
  const pages = htmlFiles(root);
  for (const m of menu) if (!pages.includes(m)) errors.push(`${m}: trang trong menu chưa có`);
  for (const page of pages) {
    const html = readFileSync(join(root, page), 'utf8');
    if (/http-equiv="refresh"/i.test(html)) continue; // trang chuyển hướng
    const dir = posix.dirname(page);
    const toRoot = (h) => posix.normalize(posix.join(dir, h));
    const nav = region(html, /<nav class="nav-links"[\s\S]*?<\/nav>/);
    if (!nav) { errors.push(`${page}: thiếu <nav class="nav-links">`); continue; }
    const items = links(nav);
    const got = items.map((a) => toRoot(a.href || ''));
    if (JSON.stringify(got) !== JSON.stringify(menu)) errors.push(`${page}: menu lệch site.json (${got.join(', ')})`);
    const cur = items.filter((a) => a.current).map((a) => toRoot(a.href));
    const expect = page.startsWith(`${OUT}/`) ? `${OUT}/index.html` : page;
    if (menu.includes(expect) && (cur.length !== 1 || cur[0] !== expect)) errors.push(`${page}: cần đúng một aria-current="page" trỏ ${expect}, có ${cur.length}`);
    const foot = region(html, /<footer class="site"[\s\S]*?<\/footer>/);
    if (!foot) errors.push(`${page}: thiếu <footer class="site">`);
    else {
      const fl = links(foot).map((a) => toRoot(a.href || ''));
      if (!menu.every((m) => fl.includes(m))) errors.push(`${page}: footer thiếu mục menu`);
    }
    // 4: link nội bộ
    for (const m of html.matchAll(/\b(?:href|src)="([^"]*)"/g)) {
      const raw = decode(m[1]);
      if (!raw || /^([a-z][a-z0-9+.-]*:|#|\/\/)/i.test(raw)) continue;
      const path = raw.split(/[?#]/)[0];
      if (!path) continue;
      const target = posix.normalize(posix.join(dir, path));
      if (target.startsWith('../')) { errors.push(`${page}: link ra ngoài site: ${raw}`); continue; }
      const full = join(root, target);
      if (!existsSync(full)) errors.push(`${page}: link hỏng: ${raw}`);
      else if (statSync(full).isDirectory() || path.endsWith('/')) errors.push(`${page}: link tới thư mục, file:// không mở được: ${raw} (trỏ …/index.html)`);
    }
  }
  // 5: Docs
  try {
    for (const s of staleFiles(root).stale) errors.push(`${s}: trang Docs cũ — chạy build-docs.mjs`);
  } catch (e) {
    errors.push(`Docs: không kiểm được (${e.message.split('\n')[0]})`);
  }
  return errors;
}

function main() {
  const args = process.argv.slice(2);
  const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
  const root = resolve(opt('--root') || 'docs');
  const source = opt('--source') ? resolve(opt('--source')) : undefined;
  const errors = checkSite(root, { source });
  for (const e of errors) console.error(e);
  if (errors.length) { console.error(`check-site: ${errors.length} lỗi`); process.exit(1); }
  console.log('check-site: PASS');
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) main();
