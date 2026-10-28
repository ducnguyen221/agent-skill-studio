// Khuôn chung của mọi trang site: <head>, header (menu + aria-current), footer.
// Cấu hình riêng mỗi repo nằm ở docs/assets/ds/site.json (install.mjs tạo bản mẫu, chủ repo sửa).
import { esc } from './md.mjs';

export const DEFAULT_MENU = [
  { href: 'index.html', label: 'Trang chủ' },
  { href: 'about/index.html', label: 'Giới thiệu' },
  { href: 'install/index.html', label: 'Cài đặt' },
  { href: 'guide/index.html', label: 'Hướng dẫn' },
  { href: 'flow/index.html', label: 'Luồng & quy trình' },
  { href: 'principles/index.html', label: 'Nguyên tắc' },
  { href: 'docs/index.html', label: 'Docs' },
];

export const DEFAULT_CONFIG = {
  name: 'Tên sản phẩm',
  tagline: 'Một câu nói lợi ích chính cho người đọc.',
  repo: 'https://github.com/ducnguyen221/<repo>',
  site: 'https://ducnguyen.vn/<repo>/',
  logo: 'assets/logo-128.png',
  license: 'MIT',
  year: 2026,
  menu: DEFAULT_MENU,
  resources: [
    { href: 'https://github.com/ducnguyen221/<repo>', label: 'GitHub' },
    { href: 'https://github.com/ducnguyen221/<repo>/blob/main/CHANGELOG.md', label: 'Changelog' },
  ],
};

export const THEME_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const GH_ICON = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .5a11.5 11.5 0 0 0-3.6 22.4c.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.4-3.9-1.4-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.3 1.2a11.4 11.4 0 0 1 6 0C17.3 4.6 18.3 5 18.3 5c.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A11.5 11.5 0 0 0 12 .5Z"/></svg>';

export function header(cfg, rel, active) {
  const items = cfg.menu.map((m) => m.href === active
    ? `      <a href="${rel}${m.href}" class="active" aria-current="page">${esc(m.label)}</a>`
    : `      <a href="${rel}${m.href}">${esc(m.label)}</a>`).join('\n');
  return `<a class="skip" href="#main">Bỏ qua điều hướng</a>
<header class="site" id="siteHeader">
  <div class="wrap nav">
    <a class="brand" href="${rel}index.html"><img src="${rel}${cfg.logo}" alt="">${esc(cfg.name)}</a>
    <nav class="nav-links" aria-label="Điều hướng chính">
${items}
    </nav>
    <a class="btn btn-ghost btn-sm gh" href="${esc(cfg.repo)}" target="_blank" rel="noopener">${GH_ICON}<span>GitHub</span></a>
    <button class="theme-btn" type="button" data-ds-theme-toggle aria-label="Giao diện">${THEME_ICON}</button>
  </div>
</header>`;
}

export function footer(cfg, rel) {
  const product = cfg.menu.map((m) => `          <a href="${rel}${m.href}">${esc(m.label)}</a>`).join('\n');
  const res = cfg.resources.map((r) => `          <a href="${esc(r.href)}" target="_blank" rel="noopener">${esc(r.label)}</a>`).join('\n');
  return `<footer class="site">
  <div class="wrap">
    <div class="foot">
      <div>
        <a class="brand" href="${rel}index.html"><img src="${rel}${cfg.logo}" alt="" width="26" height="26">${esc(cfg.name)}</a>
        <p class="foot-tag">${esc(cfg.tagline)}</p>
      </div>
      <div class="foot-links">
        <div class="foot-col">
          <b>Sản phẩm</b>
${product}
        </div>
        <div class="foot-col">
          <b>Tài nguyên</b>
${res}
        </div>
      </div>
    </div>
    <div class="foot-bottom">
      <span>© ${cfg.year} Nguyễn Quang Đức · ${esc(cfg.license)}</span>
      <span class="lic">${esc(cfg.license)} License · giữ credit tác giả</span>
    </div>
  </div>
</footer>`;
}

/** Một trang hoàn chỉnh. `rel` = đường từ trang về gốc site ("" hoặc "../" …); `path` = đường trang tính từ gốc. */
export function page({ cfg, rel, path, active, title, description, main, sprite = '', version }) {
  const v = version ? `?v=${version}` : '';
  return `<!doctype html>
<html lang="vi" data-lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<link rel="canonical" href="${esc(cfg.site)}${path === 'index.html' ? '' : path.replace(/index\.html$/, '')}">
<link rel="icon" href="${rel}${cfg.logo}">
<link rel="stylesheet" href="${rel}assets/ds/site.css${v}">
</head>
<body>
<canvas id="netbg" aria-hidden="true"></canvas>
${sprite}${header(cfg, rel, active)}
<main id="main">
${main}
</main>
${footer(cfg, rel)}
<script src="${rel}assets/ds/site.js${v}"></script>
</body>
</html>
`;
}
