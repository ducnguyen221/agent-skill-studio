#!/usr/bin/env node
// Sinh 6 trang viết tay của site (Trang chủ, Giới thiệu, Cài đặt, Cách dùng, Luồng & quy trình, Nguyên tắc).
// Trang Docs do build-docs.mjs dựng. Chữ nguồn: plans/site-content/CONTENT.md trong sổ OpcOS (đã đóng gói, có nguồn file:dòng).
// Dùng: node gen-pages.mjs [--root ..]   (mặc định root = thư mục docs/ chứa tools/)
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { esc } from './md.mjs';
import { page } from './shell.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const root = resolve(args.includes('--root') ? args[args.indexOf('--root') + 1] : join(HERE, '..'));
const cfg = JSON.parse(readFileSync(join(root, 'assets/ds/site.json'), 'utf8'));
cfg.dsVersion = JSON.parse(readFileSync(join(root, 'assets/ds/ds-lock.json'), 'utf8')).version;

const SPRITE = `<!-- biểu tượng cho infographic (.ig-*): <svg class="ig-ico"><use href="#i-..."/></svg> -->
<svg class="ig-sprite" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
  <symbol id="i-chat" viewBox="0 0 24 24"><path d="M20 11.5a8 8 0 0 1-11.7 7.1L4 20l1.1-4A8 8 0 1 1 20 11.5Z"/><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01"/></symbol>
  <symbol id="i-book" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/><path d="M9 7h7M9 11h5"/></symbol>
  <symbol id="i-tool" viewBox="0 0 24 24"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4Z"/></symbol>
  <symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3 5 6v5c0 4.3 2.9 7.8 7 9.5 4.1-1.7 7-5.2 7-9.5V6Z"/><path d="m9 12 2 2 4-4"/></symbol>
  <symbol id="i-evidence" viewBox="0 0 24 24"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z"/><path d="M14 3v6h6"/><path d="m9 15 2 2 4-4"/></symbol>
  <symbol id="i-check" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16 9.5"/></symbol>
  <symbol id="i-lock" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/><path d="M12 15v2"/></symbol>
  <symbol id="i-archive" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9"/><path d="M10 13h4"/></symbol>
</svg>
`;

// ---- trợ giúp dựng HTML -------------------------------------------------
/** Văn bản thường → HTML: thoát ký tự, `mã` thành <code>, **đậm** thành <b>. */
const I = (s) => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
const ico = (n) => `<svg class="ig-ico"><use href="#i-${n}"/></svg>`;
const hero = (eyebrow, h1, lead) => `<section class="page-hero"><div class="wrap">
  <span class="eyebrow"><span class="dot"></span>${I(eyebrow)}</span>
  <h1>${I(h1)}</h1>
  <p class="lead">${I(lead)}</p>
</div></section>`;
const sec = (head, body, sub) => `<section><div class="wrap">
  <div class="sec-head"><h2>${I(head)}</h2>${sub ? `<p>${I(sub)}</p>` : ''}</div>
${body}
</div></section>`;
const table = (heads, rows) => `  <div class="tbl-wrap"><table class="tbl"><thead><tr>${heads.map((h) => `<th scope="col">${I(h)}</th>`).join('')}</tr></thead>
  <tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i === 0 ? `<td class="lbl">${I(c)}</td>` : `<td>${I(c)}</td>`)).join('')}</tr>`).join('\n')}</tbody></table></div>`;
const code = (title, text) => {
  const body = esc(text).split('\n').map((l) => (/^\s*#/.test(l) ? `<span class="cm">${l}</span>` : l)).join('\n');
  return `  <div class="code-card"><div class="code-top"><span class="fn">${I(title)}</span><button class="copy-btn" type="button"><span class="lbl">Sao chép</span></button></div>
  <div class="code-scroll"><pre><code>${body}</code></pre></div></div>`;
};
const step = (n, h, html) => `  <div class="step"><div class="num">${n}</div><div class="body"><h3>${I(h)}</h3>${html}</div></div>`;
const p = (s) => `<p>${I(s)}</p>`;
const note = (kind, label, s) => `  <p class="note${kind ? ' ' + kind : ''}"><b>${I(label)}</b> ${I(s)}</p>`;
const card = (h, s, ic, cls = '') => `<div class="card reveal">${ic ? `<div class="ficon${cls ? ' ' + cls : ''}">${ico(ic)}</div>` : ''}<h3>${I(h)}</h3><p>${I(s)}</p></div>`;
const igStep = (i, ic, h, s, extra = '') => `      <li class="ig-step" style="--i:${i}"><div class="ig-node">${ico(ic)}<span class="ig-num">${i + 1}</span></div><div class="ig-body"><h3>${I(h)}</h3><p>${I(s)}</p>${extra}</div></li>`;
const gate = (b, s) => `<p class="ig-gate">${ico('shield')}<span><b>${I(b)}</b> · ${I(s)}</span></p>`;
const exit = (b, s) => `<p class="ig-exit">${ico('lock')}<span><b>${I(b)}</b> · ${I(s)}</span></p>`;
const ig = (title, steps, horizontal = true) => `  <div class="ig c-acc reveal">
    <p class="ig-title">${I(title)}</p>
    <ol class="ig-track${horizontal ? ' ig-h' : ''}">
${steps.join('\n')}
    </ol>
  </div>`;
const notes = (list) => `  <div class="ig-notes">\n${list.map(([ic, b, s]) => `    <p class="ig-note">${ico(ic)}<span><b>${I(b)}</b> ${I(s)}</span></p>`).join('\n')}\n  </div>`;

const pages = {};
const add = (path, active, title, description, main) => { pages[path] = { path, active, title, description, main }; };

// ---- Trang chủ ----------------------------------------------------------
add('index.html', 'index.html', 'Agent Skill Studio · Trang chủ',
  'Bộ chuẩn và công cụ để tạo, kiểm, đo và phân phối Agent Skills cho Claude Code, Codex và Antigravity.',
  `<section class="page-hero split"><div class="wrap">
  <div>
    <span class="eyebrow"><span class="dot"></span>Xưởng skill cho ba agent</span>
    <h1>Tạo Agent Skill chạy được trên cả ba agent, có bằng chứng</h1>
    <p class="lead">Agent Skill Studio là bộ chuẩn và công cụ để tạo, kiểm, cải tiến, đo và phân phối Agent Skills dùng chung cho Claude Code, OpenAI Codex và Google Antigravity, luôn theo bộ quy tắc viết skill tốt mới nhất.</p>
    <div class="hero-cta"><a class="btn btn-primary" href="install/index.html">Cài đặt</a><a class="btn btn-ghost" href="guide/index.html">Xem cách dùng</a></div>
    <div class="tech-badges"><span class="tb local"><span class="g"></span>Kiểm ngoại tuyến</span><span class="tb"><span class="g"></span>Python, không cần pip install</span><span class="tb gold"><span class="g"></span>Mã nguồn mở MIT</span></div>
  </div>
  <figure class="hero-media"><img src="assets/hero.webp" width="1200" height="800" alt="Minh hoạ dây chuyền dựng skill: khối và thẻ skill được đo, đối chiếu với phiếu chuẩn rồi gửi tới ba agent"></figure>
</div></section>
${sec('Vấn đề nó giải quyết', `  <p>Viết vài file Markdown chưa đủ làm nên một skill tốt. Skill hay hỏng ở năm chỗ, và Studio xử lý từng chỗ.</p>
  <div class="grid-3">
    ${card('Gọi sai lúc', 'Agent không gọi skill khi cần, hoặc gọi nhầm khi không cần, vì phần mô tả (`description`) mơ hồ. Studio có luật viết mô tả.', 'chat')}
    ${card('Skill dài, tốn ngữ cảnh', 'Nhồi mọi thứ vào một file thì tốn ngữ cảnh. Studio dùng cấu trúc nạp từng phần.', 'book', 'gold')}
    ${card('Hỏng ở máy khác', 'Chạy được ở máy tác giả nhưng hỏng ở máy hay agent khác. Studio dùng chuẩn mang đi được giữa ba agent.', 'tool')}
    ${card('Cấm chỉ bằng chữ', 'Điều cấm chỉ nằm trên chữ «MUST», không có rào thật. Studio đòi cổng thật cho việc rủi ro.', 'lock', 'ok')}
    ${card('Nói «đã test» không bằng chứng', 'Studio đếm lại bằng chứng đo thay vì tin lời khai.', 'evidence')}
  </div>`)}
${sec('Điểm nổi bật', `  <div class="grid-2">
    ${card('1. Kiểm hoàn toàn ngoại tuyến', 'Lệnh `check` đọc cấu trúc skill, báo lỗi theo mã, không gọi model nào và không sửa file.', 'shield')}
    ${card('2. Một bộ luật, ba agent', 'Một bộ luật viết skill theo chuẩn mở Agent Skills; khác biệt riêng từng agent được tách riêng, không trộn vào skill.', 'book', 'gold')}
    ${card('3. Không pass giả', 'Chưa đo bằng model thật thì ghi `not_run`. Cổng kiểm tự đếm lại bằng chứng, không tin con số khai.', 'evidence', 'ok')}
    ${card('4. Gói phát hành sạch', '`package` chỉ đóng file chạy, bỏ bài test, đáp án, cache; gặp tên giống secret thì dừng.', 'archive')}
  </div>`)}
${sec('Ai dùng', `  <div class="grid-2">
    ${card('Người viết skill', 'Cho đội hoặc cộng đồng, muốn skill chạy được trên cả ba agent.')}
    ${card('Người quản lý thư viện skill', 'Cần nhìn cả thư viện một lượt: skill nào lỗi, đã cài ở đâu, cặp nào có thể trùng.')}
    ${card('Agent', 'Khi được nhờ «tạo skill», «kiểm skill», «sửa skill», agent gọi `skill-creator-studio` và làm theo quy trình.')}
    ${card('Hệ OpcOS', 'Studio là xưởng chuẩn hoá skill (Skill Factory) cho các plugin khác.')}
  </div>`)}
${sec('Từ ý tưởng tới skill phát hành', `${ig('Năm bước, lỗi thì sửa rồi kiểm lại', [
  igStep(0, 'chat', 'Ý tưởng', 'Một việc lặp lại.'),
  igStep(1, 'book', 'Viết 3 ca thử trước', 'Có ca nên gọi và ca không nên gọi.', `<p>Nhánh phụ: đo model thật, có và không skill. Chưa đo = <code>not_run</code>.</p>`),
  igStep(2, 'tool', '`new`: dựng khung', 'Sinh skill và bộ eval rỗng tách riêng.'),
  igStep(3, 'shield', '`check`: kiểm tĩnh', '0 lỗi mới qua.', gate('Cổng', 'lỗi → sửa → kiểm lại')),
  igStep(4, 'archive', '`package` / `install`', 'Phát hành.'),
])}`)}
${sec('Một nguồn, ba agent', `  <div class="grid-3">
    ${card('Chuẩn chung', 'Một bộ luật viết skill, đi cùng bản gốc `skills/skill-creator-studio`.', 'book', 'gold')}
  </div>
  <p class="lead" style="margin:16px 0;text-align:center"><code>studio.py install</code> ↓</p>
  <div class="grid-3">
    ${card('Claude Code', 'Cài vào `.claude/skills/`', 'tool')}
    ${card('Codex', 'Cài vào `.agents/skills/`', 'tool')}
    ${card('Antigravity', 'Cài vào `.agents/skills/` hoặc `~/.gemini/config/skills/`', 'tool')}
  </div>`)}
${sec('Bắt đầu từ đâu', `${step(1, 'Cài', p('Cài plugin vào Claude Code hoặc Codex (trang Cài đặt). Cần Python 3.9 trở lên, không cần `pip install`.'))}
${step(2, 'Thử kiểm một skill có sẵn', code('Terminal', 'python3 studio.py check skills/skill-creator-studio'))}
${step(3, 'Đọc file lõi', p('Đọc `standards/SKILL_AUTHORING_STANDARD.md` để hiểu bộ luật viết skill (có ở trang Docs).'))}
${step(4, 'Tạo skill đầu tiên', p('Nói với agent «Create a portable Skill for …», hoặc tự chạy `studio.py new`.'))}
${step(5, 'Viết ít nhất 3 ca thử', p('Có ca nên gọi và ca không nên gọi, trước khi viết dài; rồi `check` lại.'))}`)}
${sec('Tác giả và giấy phép', `  <div class="grid-2">
    <div class="card author" id="tac-gia"><div class="avatar" aria-hidden="true">QĐ</div><div><h3>Nguyễn Quang Đức (Tobi)</h3><p>Sáng lập và CEO KPIM, đồng sáng lập COMPA Class; làm và giảng dạy Data/AI tại Việt Nam. <a href="https://ducnguyen.vn" target="_blank" rel="noopener">ducnguyen.vn</a> · GitHub <a href="https://github.com/ducnguyen221" target="_blank" rel="noopener">@ducnguyen221</a>.</p></div></div>
    ${card('Giấy phép MIT', 'Được dùng, sửa, phân phối lại, kể cả thương mại, miễn giữ thông báo bản quyền của Nguyễn Quang Đức. Skill do Studio sinh ra cho dự án khác thuộc về chủ dự án đó.', 'shield', 'ok')}
  </div>
${note('', 'Nguồn tham khảo:', 'Studio có tham khảo cấu trúc công khai của `robonuggets/skill-creator-plus` (MIT) nhưng không chép mã của repo đó.')}`)}
<section class="final"><div class="wrap">
  <h2>Bắt đầu trong vài phút</h2>
  <p>Cài, thử <code>check</code> một skill có sẵn, rồi tạo skill đầu tiên.</p>
  <div class="hero-cta"><a class="btn btn-primary" href="install/index.html">Cài đặt</a><a class="btn btn-ghost" href="guide/index.html">Xem cách dùng</a></div>
</div></section>`);

// ---- Cài đặt ------------------------------------------------------------
add('install/index.html', 'install/index.html', 'Cài đặt · Agent Skill Studio',
  'Ba cách cài Agent Skill Studio: plugin, studio.py install cho từng agent, và mẫu luật cho dự án khác.',
  `${hero('Cài đặt', 'Cài theo cách hợp với agent của bạn', 'Yêu cầu: Python 3.9 trở lên, chỉ thư viện chuẩn, không cần `pip install`. Lệnh chạy tại gốc repo (trên Windows có thể gõ `python` thay `python3`).')}
${sec('Cách 1 — Cài như plugin', `  <p>Gói plugin chỉ chứa thư mục \`skills/\`. Manifest nằm ở \`.claude-plugin/\` (Claude Code) và \`.codex-plugin/\` (Codex).`.replace(/\\`/g, '`') + `</p>
${step(1, 'Claude Code', p('Gõ trong Claude Code:') + code('Claude Code', '/plugin marketplace add ducnguyen221/agent-skill-studio\n/plugin install agent-skill-studio@agent-skill-studio'))}
${step(2, 'Codex', p('Repo có manifest `.codex-plugin/plugin.json` (tên `agent-skill-studio`, bản 0.3.0). Chạy trong terminal:') + code('Codex CLI', 'codex plugin marketplace add ducnguyen221/agent-skill-studio\ncodex plugin add agent-skill-studio@agent-skill-studio'))}
${step(3, 'Antigravity', p('Repo không có manifest plugin cho Antigravity; dùng Cách 2.'))}
${note('warn', 'Chưa kiểm:', 'dạng nguồn GitHub `ducnguyen221/agent-skill-studio` chưa chạy thử trên máy viết site; cùng lệnh với nguồn là thư mục checkout đã chạy thật cho cả Claude Code và Codex. Cờ lấy từ `claude plugin --help` và `codex plugin --help`.')}`)}
${sec('Cách 2 — Cài riêng một skill bằng studio.py install', `  <p>\`install\` sao chép có kiểm tra, không ghi đè nếu thiếu \`--force\`. \`--workspace\` phải là thư mục có sẵn.`.replace(/\\`/g, '`') + `</p>
${code('Terminal', `# vào một dự án (thư mục khám phá của agent trong dự án)
python3 studio.py install skills/skill-creator-studio --agent claude --workspace .        # .claude/skills/
python3 studio.py install skills/skill-creator-studio --agent codex --workspace .         # .agents/skills/
python3 studio.py install skills/skill-creator-studio --agent antigravity --workspace .   # .agents/skills/
# cho cả tài khoản người dùng (Claude không hỗ trợ)
python3 studio.py install skills/skill-creator-studio --agent codex --user                # ~/.agents/skills/
python3 studio.py install skills/skill-creator-studio --agent antigravity --user          # ~/.gemini/config/skills/`)}
${table(['Agent', '`--workspace`', '`--user`', 'Gọi skill'], [
  ['Claude Code', '`.claude/skills/<tên>`', '**không hỗ trợ** (thoát 2); tự chép vào `~/.claude/skills/`', '`/skill-creator-studio`'],
  ['Codex', '`.agents/skills/<tên>`', '`~/.agents/skills/<tên>`; `~/.agents` phải có sẵn', '`$skill-creator-studio` hoặc `/skills`'],
  ['Antigravity', '`.agents/skills/<tên>`', '`~/.gemini/config/skills/<tên>` (App, IDE); `~/.gemini/config` phải có sẵn; bản CLI dùng đích khác, `install` không ghi vào đó', 'theo IDE/CLI, thường `/skill-name`'],
])}
${note('warn', 'Lưu ý:', 'Codex và Antigravity dùng chung `.agents/skills/` trong dự án, nên cài một lần là cả hai thấy. Đừng cài cùng skill hai lần dưới hai tên khác nhau, vì chúng sẽ tranh nhau được gọi.')}`)}
${sec('Cách 3 — Mẫu luật cho dự án khác', `  <p>Chép \`templates/starter-project/\` vào dự án đích: \`AGENTS.md\` là bộ luật chung duy nhất; \`CLAUDE.md\` nạp nó bằng dòng \`@AGENTS.md\`; Codex đọc thẳng \`AGENTS.md\`; \`GEMINI.md\` trỏ về \`AGENTS.md\`. Mỗi file có sẵn một dòng \`install\` đúng cờ.`.replace(/\\`/g, '`') + `</p>`)}
${sec('Kiểm sau khi cài', `${code('Terminal', `python3 studio.py --version                       # in 0.3.0
python3 studio.py doctor                          # quét skills/ của repo, chỉ báo cáo; thoát 0 sạch, 1 có phát hiện, 2 không quét được
python3 studio.py doctor --roots ".claude/skills" # quét gốc skill khác (ngoài repo bắt buộc --roots hoặc --roots-file)
python3 studio.py check skills/skill-creator-studio`)}
  <p>Rồi kiểm trong agent: Claude Code tìm được <code>/skill-creator-studio</code> (và <code>/context</code> cho thấy <code>CLAUDE.md</code> đã nạp <code>@AGENTS.md</code>); Codex liệt kê <code>/skills</code> hoặc gọi <code>$skill-creator-studio</code>; Antigravity kiểm <code>.agents/skills/</code> đã được nhận và tên skill hiện ra. Có thể hỏi agent: «Which repo instruction files and Skill names are active?».</p>`)}
${sec('Nâng cấp và gỡ', `  <div class="grid-2">
    ${card('Nâng cấp', 'Bản cài bằng `install`: chạy lại với `--force`; bản cũ chuyển sang `.skill-studio-backups/` (ngoài gốc skill), rồi bản mới thay vào. Đọc `CHANGELOG.md` mục 0.2.0 trước khi nâng từ 0.1.0 vì có đổi hợp đồng.')}
    ${card('Gỡ', 'Bản cài bằng `install` là một thư mục thường dưới các đường ở bảng trên; xoá thư mục đó là gỡ.')}
  </div>
${code('Plugin — nâng cấp và gỡ', `# Claude Code
claude plugin marketplace update agent-skill-studio
claude plugin update agent-skill-studio@agent-skill-studio
claude plugin uninstall agent-skill-studio@agent-skill-studio
# Codex
codex plugin marketplace upgrade agent-skill-studio
codex plugin add agent-skill-studio@agent-skill-studio      # cài lại bản mới
codex plugin remove agent-skill-studio@agent-skill-studio`)}
${note('warn', 'Lưu ý:', '`claude plugin update` có thể không hạ phiên bản; muốn về bản cũ thì gỡ rồi cài lại từ tag cũ.')}`)}
${sec('Giới hạn khi cài', `  <div class="faq">
    <details><summary>Thư mục skill là symlink hoặc junction?</summary><p><code>install</code> thoát 2 (cờ <code>--allow-root-link</code> cho phép có chủ ý và in đích thật); đích là link thì thoát 1.</p></details>
    <details><summary>Trên macOS, <code>new --output</code> dưới <code>/tmp</code> bị từ chối?</summary><p>Đúng: <code>/tmp</code> và <code>/var</code> là symlink. Dùng thư mục dưới <code>$HOME</code>.</p></details>
    <details><summary>Antigravity có đọc <code>references/</code> không?</summary><p>Chưa chạy thật để biết (<code>not_run</code>).</p></details>
  </div>`)}`);

// ---- Cách dùng ----------------------------------------------------------
const modeSteps = (list) => `<ol>${list.map((s) => `<li>${I(s)}</li>`).join('')}</ol>`;
add('guide/index.html', 'guide/index.html', 'Cách dùng · Agent Skill Studio',
  'Ba chế độ NEW, AUDIT, REFINE của skill-creator-studio, các lệnh studio.py, skill skill-curator và ba ví dụ đầu-cuối.',
  `${hero('Cách dùng', 'Ba chế độ, bộ lệnh đủ dùng, ví dụ chép được', 'Khi được gọi, skill `skill-creator-studio` chọn một trong ba nhánh NEW, AUDIT, REFINE. Bảy luật luôn giữ ở mọi lượt: AUDIT báo trước khi sửa; mặc định portable; hướng dẫn tối thiểu đủ dùng; rủi ro quyết mức tự do; eval nằm ngoài gói chạy; không bịa kết quả test; xin kết luận và bằng chứng, không xin suy luận nội bộ.')}
${sec('NEW — tạo skill mới', `  <p><b>Khi nào:</b> có một việc lặp lại mà chưa có skill riêng. <b>Câu nói mẫu:</b> «Create a portable Skill for weekly sales reconciliation with a checklist and separate evaluation tests.»</p>
${step(1, 'Xác định', p('Một việc, câu nên gọi, câu không nên gọi, đầu vào/ra, tác dụng phụ. Xong khi giải thích được trong hai câu.'))}
${step(2, 'Viết ca thử trước', p('Ít nhất 3 ca thử thật và kế hoạch đo không skill, trước khi viết dài.'))}
${step(3, 'Dựng khung', code('Terminal', 'python3 studio.py new <tên> --description "<việc>. Use when <khi nào>." --output <đích>') + p('Thêm `--lang vi` hoặc `--full` khi cần.'))}
${step(4, 'Viết thân thật', p('Thay chữ nháp; thêm `references/`, `scripts/`, `assets/` chỉ khi cần. Không phát hành khi còn dấu `STUDIO-DRAFT`.'))}
${step(5, 'Kiểm', p('`validate <đường> --require-evals`, rồi `evals`. Lỗi thì quay lại bước 4.'))}
${step(6, 'Đóng gói', p('Ghi rõ đã đo trên agent nào, rồi đóng gói khi qua cổng phát hành.'))}
${note('ok', 'Đầu ra:', 'thư mục skill mới, thư mục `evals/<tên>` tách riêng, kết quả kiểm chạy được.')}`)}
${sec('AUDIT — kiểm, không sửa', `  <p><b>Khi nào:</b> cần chấm, rà, review một skill hay cả thư viện. <b>Câu nói mẫu:</b> «Audit the skill in the attached broken-skill folder and report failures without making changes.»</p>
${step(1, 'Chạy kiểm tĩnh', p('`audit <thư mục skill>` hoặc `audit --all`; nhiều thư mục skill thì `doctor --roots "<dir1>;<dir2>"`.'))}
${step(2, 'Rà tay', p('Theo `references/AUDIT_CHECKLIST.md` (map 16 luật sang điều quan sát được).'))}
${step(3, 'Tra nguồn', p('Cần nguồn của một luật thì đọc `references/SOURCE_NOTES.md`.'))}
${step(4, 'Viết báo cáo', p('Dạng `Đường:dòng | Luật | Mức | Bằng chứng | Cách sửa | Rủi ro`, tách phần máy kiểm và phần người kiểm.'))}
${step(5, 'Dừng trước khi sửa', p('Hỏi người dùng sửa mục số mấy.'))}
${note('ok', 'Đầu ra:', 'báo cáo có bằng chứng; không file nào bị sửa.')}`)}
${sec('REFINE — sửa theo bằng chứng', `  <p><b>Khi nào:</b> skill hỏng khi dùng thật, hoặc có bằng chứng mới. <b>Câu nói mẫu:</b> «Our reporting skill skips its validation step. Propose a minimal fix and an A/B test before removing old instructions.»</p>
${step(1, 'Ghi lại lỗi', p('Câu lệnh, model/agent, kỳ vọng và thực tế; xếp loại lỗi (kích hoạt, thiếu reference, thực thi, chất lượng đầu ra).'))}
${step(2, 'Tìm luật nhỏ nhất gây lỗi', p('Đề xuất diff và ca thử bị ảnh hưởng.'))}
${step(3, 'Chỉ áp phần được duyệt', p('Xoá luật cũ bị thay trong cùng lượt.'))}
${step(4, 'Kiểm lại', p('Kiểm tĩnh và eval nhắm đích; sửa liên quan an toàn thì thử cả ca cho phép và ca chặn ở phiên mới.'))}
${step(5, 'Báo', p('Danh sách thay đổi, file chạm, kiểm đã chạy, phần chưa đo bằng model, cách hoàn tác.'))}
${note('ok', 'Đầu ra:', 'thay đổi nhỏ có kiểm hồi quy và ghi chú phát hành.')}
${note('', 'Câu không gọi skill', '(ca âm trong bộ eval): «Write a Python function that sorts a list of integers…», «Explain how a person installs a plugin from a marketplace…», «List the names of the skill folders…».')}`)}
${sec('Các lệnh của studio.py', `${table(['Lệnh', 'Việc', 'Cờ chính', 'Ví dụ'], [
  ['`new`', 'dựng skill mới + bộ eval rỗng tách riêng', '`--description` (bắt buộc), `--output`, `--eval-root`, `--lang {en,vi}`, `--full`', '`python3 studio.py new my-skill --output skills --description "Does X. Use when Y."`'],
  ['`check`', 'kiểm tĩnh một skill (thư mục hoặc `SKILL.md`) hoặc file workflow, file luật có `type:`; không sửa file', '`--all`, `--require-evals`, `--eval-root`, `--target {portable,claude-code}`, `--json`', '`python3 studio.py check skills/skill-creator-studio`'],
  ['`validate`', 'bí danh của `check` (cùng cờ, mã thoát, JSON)', 'như `check`', '`python3 studio.py validate --all --require-evals`'],
  ['`audit`', 'bí danh của `check`; đối số chỉ nhận thư mục skill', 'như `check`', '`python3 studio.py audit skills/skill-creator-studio`'],
  ['`evals`', 'kiểm schema bộ eval (không gọi model); `--all` thêm cổng `model_evaluated`', '`--all`, `--eval-root`, `--export agentskills`, `--out`, `--force`, `--json`', '`python3 studio.py evals --all`'],
  ['`package`', 'đóng ZIP chỉ gồm file chạy', '`--out`, `--force`', '`python3 studio.py package skills/skill-creator-studio --out dist`'],
  ['`install`', 'chép skill vào thư mục khám phá của agent', '`--agent {claude,codex,antigravity}` (bắt buộc), `--workspace` hoặc `--user`, `--force`, `--allow-root-link`', '`python3 studio.py install skills/skill-creator-studio --agent codex --workspace .`'],
  ['`doctor`', 'quét nhiều gốc skill, chỉ báo cáo', '`--roots`, `--roots-file`, `--profile {portable,opcos}`, `--target`, `--include-cache`, `--skip-marker`, `--baseline`, `--json`, `--out`, `--fail-on {error,warn,new}`', '`python3 studio.py doctor --roots "~/.claude/skills;.agents/skills"`'],
  ['`catalog`', 'liệt kê mọi skill nguồn thành một bảng; chỉ đọc', '`--roots-from opcos`, `--roots`, `--installed`, `--overlap`, `--json`, `--out`, `--md`', '`python3 studio.py catalog --roots ".claude/skills;.agents/skills" --overlap`'],
  ['`fmt`', 'kiểm (mặc định) hoặc sửa kiểu trình bày Markdown; không đổi chữ của thân', '`--all`, `--check`/`--fix`, `--no-backup`, `--profile`, `--json`', '`python3 studio.py fmt --check --all`'],
])}
  <p>Skill <code>skill-curator</code> dùng lệnh <code>catalog</code> để nhìn cả thư viện: skill nào có, đã cài ở đâu, cặp nào có thể trùng. Khác với <code>skill-creator-studio</code> chỉ lo một skill mỗi lần; <code>skill-curator</code> không sửa, cài hay xoá skill nào.</p>
  <p>Cờ đầy đủ: <code>python studio.py &lt;lệnh&gt; --help</code>. Cờ chung: <code>--version</code> in phiên bản; <code>--help</code> cho mọi lệnh.</p>
${note('warn', 'Mã lỗi hay gặp:', '`INPUT` (file ở vùng cloud/secret, placeholder cloud, hoặc là link), `EV20` (catalog hỏng hoặc lệch bằng chứng), `PACK` (gói gặp link, placeholder, cây quá lớn, file trên 25 MB…), `SEC` (tên file giống secret như `.env*`, `*.pem`), `EX1`–`EX13` (xuất eval bị từ chối). Mỗi lần từ chối in mã ra stderr và trong `--json`.')}`)}
${sec('Ba ví dụ đầu-cuối', `  <h3>Ví dụ 1 — Tạo skill mới tiếng Việt, đến lúc đóng gói</h3>
${code('Terminal', `python3 studio.py new writing-weekly-notes --output skills --lang vi \\
  --description "Writes weekly team notes from a task list. Use when asked for weekly notes."
# sinh skills/writing-weekly-notes/SKILL.md và evals/writing-weekly-notes/{cases.json, rubric.md, baselines/BASELINE.md}
python3 studio.py check skills/writing-weekly-notes      # còn cảnh báo CT9: dấu nháp chưa xoá
# viết thân thật, xoá dấu STUDIO-DRAFT, thay 3 ca nháp bằng ca thật (có ca âm), thêm mục vào evals/catalog.json
python3 studio.py validate skills/writing-weekly-notes --require-evals
python3 studio.py evals writing-weekly-notes
python3 studio.py package skills/writing-weekly-notes --out dist`)}
${note('', 'Lưu ý:', '`package` từ chối khung còn dấu nháp («cannot package an unfinished template»): khung chưa viết thì không phát hành được.')}
  <h3 style="margin-top:28px">Ví dụ 2 — Kiểm cả thư viện skill trên máy, không sửa gì</h3>
${code('Terminal', `python3 studio.py doctor --roots "~/.claude/skills;~/.agents/skills" --json --out report.json
python3 studio.py doctor --roots "~/.claude/skills;~/.agents/skills" --baseline report.json --fail-on new`)}
  <p>Lần đầu ghi báo cáo JSON; lần sau so với mốc và chỉ báo đỏ khi có cặp (skill, mã lỗi) mới mọc thêm. <code>doctor</code> không mở vùng secret, cloud hay link.</p>
  <h3 style="margin-top:28px">Ví dụ 3 — Kiểm phát hành rồi cài skill cho Codex</h3>
${code('Terminal', `python3 studio.py doctor
python3 studio.py fmt --check --all
python3 studio.py validate --all --require-evals
python3 studio.py evals --all
python3 -m unittest discover -s tests
python3 studio.py install skills/skill-creator-studio --agent codex --workspace .`)}
  <p>Năm lệnh đầu là bộ kiểm trước phát hành, đều phải thoát 0. Lệnh cuối chép skill vào <code>.agents/skills/skill-creator-studio</code>; trong Codex gõ <code>$skill-creator-studio</code> để thử.</p>`)}`);

// ---- Luồng & quy trình --------------------------------------------------
add('flow/index.html', 'flow/index.html', 'Luồng & quy trình · Agent Skill Studio',
  'Vòng đời một skill, luồng dữ liệu eval và cổng model_evaluated, cấu trúc repo.',
  `${hero('Luồng & quy trình', 'Việc chạy qua những bước nào', 'Ba luồng: vòng đời một skill, dữ liệu eval và cổng `model_evaluated`, và cấu trúc repo.')}
${sec('Luồng 1 — Vòng đời một skill', `${ig('Tám bước, từ Refine quay về Viết', [
  igStep(0, 'chat', 'Ý tưởng', 'Một việc lặp lại, có từ người dùng hay nói và một ca không nên gọi.'),
  igStep(1, 'book', 'Eval trước', 'Viết ≥3 ca thật (thường, biên, âm) và kế hoạch đo không skill, trước khi viết dài.'),
  igStep(2, 'tool', 'Viết', '`new` dựng khung; viết thân theo thứ tự luật quan trọng → mục đích → khi nào dùng/không → các bước có «xong khi» → chỉ tới reference.'),
  igStep(3, 'shield', 'Check / validate', 'Kiểm tĩnh; lỗi thì sửa rồi kiểm lại.', gate('Cổng', 'lên Candidate')),
  igStep(4, 'evidence', 'Đo model thật', 'Cùng ca, phiên mới, có và không skill, so A/B; chưa chạy thì `not_run`.', gate('Cổng', 'lên Production')),
  igStep(5, 'archive', 'Đóng gói', '`package` từ chối khi còn dấu nháp; thử `install`.'),
  igStep(6, 'check', 'Phát hành', 'Ghi CHANGELOG, tăng phiên bản, owner duyệt.'),
  igStep(7, 'tool', 'Refine', 'Dùng thật thấy lỗi → ghi bằng chứng → sửa nhỏ nhất → kiểm hồi quy; quay về Viết.', exit('Lỗi', 'quay lại Viết')),
], false)}
  <h3 style="margin:28px 0 12px">Bốn trạng thái</h3>
  <ol class="timeline"><li><span class="tnum">01</span><h3>Draft</h3><p>Đang viết, còn dấu nháp.</p></li><li><span class="tnum">02</span><h3>Candidate</h3><p><code>check</code> sạch, ≥3 tình huống, đã review nội dung.</p></li><li><span class="tnum">03</span><h3>Production</h3><p>Đo trên agent đích, owner duyệt, không lỗi an toàn.</p></li><li><span class="tnum">04</span><h3>Deprecated</h3><p>Dừng gọi, ghi đường chuyển, không xoá đột ngột.</p></li></ol>
${note('', 'Đánh phiên bản:', 'PATCH sửa chữ, link; MINOR thêm quy trình, reference, eval; MAJOR đổi trigger, hợp đồng đầu ra, quyền thực thi.')}`)}
${sec('Luồng 2 — Dữ liệu eval và cổng model_evaluated', `${ig('Từ ca thử tới cổng EV20', [
  igStep(0, 'book', 'cases.json + rubric', 'Bộ ca: câu lệnh, có nên gọi không, hành vi kỳ vọng.'),
  igStep(1, 'archive', 'Log từng lượt đo', 'Giữ ngoài repo: log từng phiên, transcript đã che.'),
  igStep(2, 'evidence', 'evidence/<lô>.json', 'Trong repo: sinh bằng `compact`, kiểm bằng `compact --verify`.'),
  igStep(3, 'shield', 'Cổng EV20', 'Đếm lại, tính lại `result`, so với khối khai.', gate('Khớp', 'thoát 0') + exit('Lệch', 'ERROR EV20, thoát 1')),
])}
${notes([['book', '`evals/catalog.json`', 'mỗi skill một mục (đường, phiên bản, agent đích, `model_evaluated`), có thể mang khối `evaluated`; mũi tên khai vào cổng.'], ['shield', 'Ngưỡng cố định', 'mỗi agent đã chạy phải đạt ngưỡng kích hoạt đúng, không kích hoạt sai, và A/B tốt hơn bản không skill. Không bao giờ sửa ngưỡng cho vừa số.']])}
  <p style="margin-top:16px"><code>result</code> nhận một trong bốn giá trị: <code>not_run</code> (không agent nào chạy), <code>below-threshold</code>, <code>partial</code> (đạt nhưng còn agent hoãn có lý do), <code>passed</code>. <code>model_evaluated: true</code> chỉ hợp lệ khi <code>passed</code>.</p>`)}
${sec('Luồng 3 — Cấu trúc repo', `${table(['Thư mục', 'Vai', 'Vào gói cài?'], [
  ['`standards/`', 'các file chuẩn cho tác giả skill', 'Không'],
  ['`skills/`', 'chỉ skill phát hành: `skill-creator-studio` (`SKILL.md`, `references/`, `scripts/` chứa engine, `assets/` chứa 2 khuôn)', '**Có** (chỉ thư mục này)'],
  ['`templates/`', '`starter-project/`: mẫu file luật cho dự án khác', 'Không'],
  ['`examples/`', 'mẫu để chép: `descriptions.md`, `eval-cases.md`, 2 skill mẫu ngắn, skill CSV `data-quality-audit`', 'Không'],
  ['`evals/`', '`catalog.json`, `RUNBOOK.md`, `tools/`, bộ eval từng skill', 'Không'],
  ['`tests/`', 'test ngoại tuyến và ca hợp đồng của dòng lệnh', 'Không'],
  ['`docs/`', 'website này', 'Không'],
])}`)}`);

// ---- Nguyên tắc ---------------------------------------------------------
const RULES = [
  ['`SK-00` Manifest portable', '`SKILL.md` mở bằng frontmatter có `name` (≤64 ký tự, chữ thường-số-gạch, khớp tên thư mục) và `description` (≤1 024 ký tự, nói làm gì + khi nào); chỉ thêm 4 khoá portable khác', 'để mọi agent đọc được cùng một file', 'MUST', '`FM1`, `FM2`, `FM4`–`FM6`, `DS1`'],
  ['`SK-01` Nạp từng phần', 'thân `SKILL.md` là bộ định tuyến, <500 dòng và <5 000 token; chi tiết ở `references/`', 'tiết kiệm ngữ cảnh, chỉ đọc khi cần', 'SHOULD', '`ST1`, `ST2`'],
  ['`SK-02` Cắt gọn', 'trước khi giữ một đoạn, hỏi: bỏ đi agent có làm sai không, có lặp file khác không', 'mỗi dòng thừa tốn token mỗi lần nạp', 'SHOULD', 'review'],
  ['`SK-03` Tự do theo rủi ro', 'việc an toàn viết văn xuôi; việc rủi ro (xoá, thanh toán, deploy) dùng script, schema, xin duyệt', 'sai ở việc rủi ro thì mất tiền hoặc dữ liệu', 'MUST khi thiết kế', 'review'],
  ['`SK-04` Thử trên model đích', 'không xoá luật theo cảm tính; chạy ≥3 tình huống, có/không skill, phiên mới', 'luật «thừa» có thể đang giữ chất lượng', 'SHOULD; MUST nếu production', 'review'],
  ['`SK-05` Ngắn, dễ kích hoạt', 'mỗi skill một nhóm việc; `description` tiếng Anh, ngôi thứ ba, có `Use when …`, cụm kích hoạt trong ~500 ký tự đầu', 'Claude Code cắt danh sách ở 1 536 ký tự; mô tả rộng thì tranh trigger', 'SHOULD', '`DS2`–`DS5`, `FM8`'],
  ['`SK-06` Quy trình kiểm được', 'mỗi bước có «Done when» và đường quay lại khi lỗi', 'agent biết lúc nào xong, lúc nào phải làm lại', 'MUST nếu nhiều bước', 'review'],
  ['`SK-07` Vòng phản hồi', 'kiểm → chẩn đoán → sửa → kiểm lại, có giới hạn số lần; lỗi nêu tên trường và giá trị đúng', 'tránh lặp vô hạn và báo xong sớm', 'MUST nếu quan trọng', 'review'],
  ['`SK-08` Mẫu, ví dụ, nhánh', 'ghi mẫu là Strict hay Flexible; 1–3 cặp vào/ra thật; một mặc định; có mục `## Gotchas`', 'ví dụ thật dạy nhanh hơn mô tả', 'SHOULD', 'review'],
  ['`SK-09` Chạy được máy khác', 'ghi công cụ, phiên bản, cách cài; đường tương đối, không đường cứng, không secret', 'skill hỏng khi rời máy tác giả', 'MUST nếu có dependency', '`ST6`, `SC3`, `SEC`'],
  ['`SK-10` Cổng thật', 'việc mất dữ liệu, tốn tiền, gửi ra ngoài phải có permission/hook/tool gate, thử cả ca cho phép và ca chặn', 'lời nhắc có thể bị bỏ qua hoặc bị nén mất', 'MUST nếu rủi ro', 'review'],
  ['`SK-11` Eval trước', 'trước khi mở rộng: ≥3 câu thật, 1 câu âm, đo không skill; eval nằm ngoài `skills/`', 'có thước trước thì mới biết sửa có tốt hơn', 'SHOULD; MUST nếu production', '`EV1`–`EV6`'],
  ['`SK-12` Luật quan trọng lên đầu', 'luật xuyên quy trình, rào an toàn, Definition of Done đặt ngay sau frontmatter', 'sau khi nén, Claude Code chỉ giữ 5 000 token đầu mỗi skill', 'SHOULD', 'review'],
  ['`SK-13` Không bắt chép suy luận', 'xin kết luận, giả định, bằng chứng, giải thích ngắn thay vì chuỗi suy nghĩ nội bộ', 'model có thể từ chối loại yêu cầu này', 'MUST', '`NM2`'],
  ['`SK-14` Chữ ép buộc có lý do', '`MUST`/`NEVER`/`ALWAYS` kèm «vì…»', 'chữ trơ làm model đời mới phản ứng quá đà', 'SHOULD', '`CT10` (WARN)'],
  ['`SK-15` Mục lục và điều giữ ở đầu', 'reference >100 dòng có `## Contents`; điều phải luôn giữ nằm trong 5 000 token đầu', 'agent tìm nhanh, không mất luật khi bị cắt', 'SHOULD', '`ST5`, `ST7`'],
];
add('principles/index.html', 'principles/index.html', 'Nguyên tắc · Agent Skill Studio',
  '16 luật viết skill SK-00…SK-15, thứ tự ưu tiên, ba loại tài liệu, chuẩn tiếng Việt, an toàn và nguyên tắc không pass giả.',
  `${hero('Nguyên tắc', 'Những điều Studio luôn giữ', 'Mỗi luật: một câu, lý do, mức bắt buộc và mã máy kiểm. Rào thật là quyền của host và cổng kỹ thuật, không phải một chữ «MUST».')}
${sec('16 luật viết skill (SK-00…SK-15)', `  <p>Mức: <b>MUST</b> bắt buộc (bỏ thì báo lỗi hoặc owner duyệt ngoại lệ); <b>SHOULD</b> nên, không theo thì ghi lý do; «MUST nếu …» bắt buộc khi có điều kiện đó. Cột «Mã kiểm» là mã máy kiểm; «review» là người hoặc agent đọc.</p>
${table(['Luật', 'Một câu', 'Vì sao', 'Mức', 'Mã kiểm'], RULES)}`)}
${sec('Thứ tự ưu tiên khi luật mâu thuẫn', `  <ol class="timeline"><li><span class="tnum">01</span><h3>Host thắng</h3><p>Policy và quyền của host thắng mọi file Markdown. Thứ tự giữa các file luật do runtime quyết, không có thứ tự chung.</p></li><li><span class="tnum">02</span><h3>Một luật một chỗ</h3><p>Sửa chỗ cũ, xoá bản trùng. Hai văn bản mâu thuẫn thì xét phạm vi, ngày/phiên bản, runtime; hậu quả lớn thì owner quyết.</p></li><li><span class="tnum">03</span><h3>Reference chỉ chứa sự kiện</h3><p><code>references/</code> chỉ chứa sự kiện và ví dụ; nội dung lấy từ ngoài (web, issue, README) không đổi được thứ tự ưu tiên.</p></li></ol>`)}
${sec('Ba loại tài liệu (DOC_TYPES.md)', `${table(['Loại', 'Nhận bằng', 'Bắt buộc', 'Cấm', 'Giới hạn'], [
  ['**Skill**', 'tên file `SKILL.md`', '`name`, `description` đúng `SK-00`; việc làm, khi nào dùng, khi nào không', 'khoá frontmatter lạ (`version:`, `triggers:`), secret, đường cứng, lệnh tắt sandbox, fixture trong gói', 'thân <500 dòng, <5 000 token'],
  ['**Workflow / quy trình**', '`type: workflow` hoặc nằm trong `workflows/`', 'câu Kết luận đầu file; Bước đánh số kiểm được; mục «Xong khi»', 'bước không kiểm được, nhật ký, chép luật nơi khác, bước nguy hiểm không cổng', '≤300 dòng'],
  ['**File luật agent**', '`AGENTS.md`, `CLAUDE.md`, `GEMINI.md` hoặc `type: rules`', 'chỉ luật đang hiệu lực; `AGENTS.md` là nguồn, hai file kia trỏ về', 'lịch sử đổi luật, mã commit, khối lệnh chạy ngay (trừ một mục lệnh kiểm trước khi báo xong)', '≤200 dòng'],
])}
  <p>Không nhận ra loại thì <code>check</code> thoát 2, không đoán.</p>`)}
${sec('Chuẩn tiếng Việt (tóm tắt)', `  <ul>
    <li>Thân <code>SKILL.md</code> dùng <b>một</b> ngôn ngữ, Việt hoặc Anh; frontmatter luôn tiếng Anh và <code>description</code> phải còn cụm <code>Use when</code>.</li>
    <li>14 quy tắc <code>V01</code>–<code>V14</code>: kết luận lên đầu; mỗi bước bắt đầu bằng động từ; câu ≤25 từ; lặp danh từ thay đại từ xa; một khái niệm một từ; đủ dấu, chuẩn NFC; ngày ISO <code>2026-10-22</code>; giữ thuật ngữ kỹ thuật tiếng Anh đã quen, lần đầu ghi «Việt (Anh)».</li>
    <li>Lint <code>VI1</code>–<code>VI5</code> đều là cảnh báo, chỉ chạy khi thân có ≥3 % chữ có dấu; dòng có <code>&lt;!-- studio:vi-ok --&gt;</code> được miễn.</li>
  </ul>`)}
${sec('An toàn và quyền (tóm tắt)', `  <div class="grid-2">
    ${card('Skill không phải rào bảo mật', 'Rào thật là quyền của host, sandbox, kiểm trước khi chạy và bước duyệt.')}
    ${card('Bốn mức hành động', 'Chỉ đọc; ghi cục bộ có thể hoàn tác; tác dụng ra ngoài (gửi mail, thanh toán, deploy, xoá) cần quyền cụ thể và cổng kỹ thuật; nguy hiểm thì không tự thêm `--force`, `--no-verify`, không tắt sandbox.')}
    ${card('Năm bước bảo vệ', 'Kế hoạch trước → kiểm độc lập → chỉ chạy phần được phép → xác minh → báo đúng việc đã làm.')}
    ${card('Gói phát hành sạch', 'Từ chối symlink, file ra ngoài gốc skill, `evals/`, `.env`, khoá/chứng chỉ, `__pycache__`, `.git`. Dữ liệu mẫu phải tổng hợp, không dùng dữ liệu khách hàng thật.')}
  </div>
${note('ok', 'Engine không nạp mã từ repo chứa nó:', 'mọi cổng chỉ đọc dữ liệu (JSON, log, Markdown).')}
${note('', 'Việc có tác dụng phụ:', 'phải thử bốn ca: cho phép, chặn, đường vòng, và thử không xâm lấn (mock hoặc staging).')}`)}
${sec('«Không pass giả» (not_run)', `${note('ok', 'Luôn làm:', 'chưa chạy model thì ghi `not_run`; trong log để trường `null` và `status: "not_run"` cho tới khi có lượt chạy thật.')}
${note('danger', 'Không bao giờ:', 'gọi skill là «production-tested» khi chưa đo; tính lời tự nhận đã pass mà không có log hay sản phẩm; tự điền điểm; coi kiểm JSON tĩnh là bằng chứng model đã làm xong ca (nó chỉ chứng minh siêu dữ liệu của ca hợp lệ).')}`)}
${sec('File luật nào nói gì, khi nào đọc', `${table(['File', 'Nói gì', 'Khi nào đọc'], [
  ['`standards/SKILL_AUTHORING_STANDARD.md`', '16 luật `SK-*`, mức, thứ tự ưu tiên, vòng đời, Definition of Done', 'đầu tiên, khi viết, kiểm hay sửa một skill'],
  ['`standards/VIETNAMESE_SKILL_WRITING.md`', '14 quy tắc thân tiếng Việt, lint `VI1`–`VI5`, bảng thuật ngữ', 'khi skill có thân tiếng Việt'],
  ['`standards/DOC_TYPES.md`', 'luật cho skill, workflow, file luật agent', 'khi soạn một trong ba loại'],
  ['`standards/HARNESSES.md`', 'khác biệt ba agent: đường cài, giới hạn, cách nạp file luật', 'khi cài hay kiểm skill trên Claude Code, Codex, Antigravity'],
  ['`standards/EVALUATION_STANDARD.md`', 'loại bài kiểm, A/B, `not_run`, khối `evaluated`, xuất agentskills', 'khi đo skill bằng model thật'],
  ['`standards/SECURITY_AND_PERMISSIONS.md`', 'mô hình đe doạ, mức rủi ro hành động, bảo mật đóng gói', 'khi skill có tác dụng phụ, hook, secret'],
  ['`standards/SOURCE_TRACEABILITY.md`', 'nguồn của từng luật, bản đồ 46 check của RoboNuggets', 'khi cần biết luật nào chính thức, luật nào là quyết định nội bộ'],
  ['`skills/skill-creator-studio/references/CORE_RULES.md`', 'bản sao **sinh tự động** của 16 luật + ưu tiên, vòng đời, DoD; đi theo gói cài', 'agent đọc khi cần xếp một phát hiện vào luật nào (không sửa tay; sửa chuẩn rồi sinh lại bằng `tests/gen_core_rules.py`)'],
  ['`skills/skill-creator-studio/scripts/studio_lint.py`', 'mã kiểm thực thi các luật máy kiểm được (ví dụ `CT10`, `VI*`)', 'khi muốn biết một mã lỗi được kiểm thế nào'],
  ['`standards/README.md`', 'bảng «đọc gì khi nào» và vị trí Studio trong hệ OpcOS', 'khi chưa biết bắt đầu từ file nào'],
])}`)}`);

// ---- ghi file -----------------------------------------------------------
for (const pg of Object.values(pages)) {
  const rel = '../'.repeat(pg.path.split('/').length - 1);
  const main = pg.main.split(/(<pre>[\s\S]*?<\/pre>)/).map((seg) => (seg.startsWith('<pre>') ? seg : seg.replace(/`([^`<>\n]+)`/g, '<code>$1</code>'))).join('');
  const html = page({ cfg, rel, path: pg.path, active: pg.active, title: pg.title, description: pg.description, main, sprite: SPRITE, version: cfg.dsVersion });
  const out = join(root, pg.path);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, html, 'utf8');
  console.log(`wrote ${pg.path}`);
}
