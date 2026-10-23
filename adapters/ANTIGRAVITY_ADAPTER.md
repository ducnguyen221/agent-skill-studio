# Google Antigravity Adapter — Agent Skills, Rules và Discovery

Checked: 2026-10-23 · nguồn đã mở lại: [Official Skills](https://antigravity.google/docs/skills) (đích workspace và toàn cục, thư mục con). [Official Rules](https://www.antigravity.google/docs/rules/): `not_run:chưa mở lại` ở lần này. Product name trong tài liệu công khai là **Google Antigravity**; "AntiCraft" không phải tên chính thức được xác minh.

## Project / global paths

- Project/workspace Skills: `.agents/skills/<skill-name>/SKILL.md`.
- Global Skills (App và IDE): `~/.gemini/config/skills/<skill-name>/SKILL.md` theo tài liệu Antigravity. Tài liệu nêu CLI dùng đích khác, `~/.gemini/antigravity-cli/skills/<skill-name>/`; lệnh `install --user` của Studio **không** ghi vào đích CLI này.
- Studio: `install --agent antigravity --user` chép vào `~/.gemini/config/skills/<tên>`; `~/.gemini/config` phải có sẵn (thiếu thì thoát 2, không tạo gì).
- Workspace instruction/rules: `AGENTS.md`, `GEMINI.md`, hoặc `.agents/rules/*.md` tùy surface và activation configuration.
- Legacy `.agent/skills` còn có thể tương thích, nhưng chuẩn repo mới nên dùng `.agents/skills`.

## Cài và kích hoạt

```bash
mkdir -p ./target-project   # --workspace phải là thư mục có sẵn, thiếu thì thoát 2
python3 studio.py install skills/skill-creator-studio --agent antigravity --workspace ./target-project
# cấp người dùng (App/IDE)
python3 studio.py install skills/skill-creator-studio --agent antigravity --user
# Trong Antigravity: dùng yêu cầu tương ứng hoặc slash-command nếu surface hỗ trợ
```

Nếu đã cài Skill tại `.agents/skills` bằng Codex, không cần cài lại để Antigravity đọc cùng dữ liệu; kiểm tra behavior trên surface được dùng.

## Thư mục con của skill

Tài liệu Antigravity liệt kê `scripts/`, `examples/` và `resources/` bên cạnh `SKILL.md`; không thấy nhắc `references/` hay `assets/`. Studio giữ `references/` và `assets/` (SK-01, progressive disclosure) và `install` chép nguyên cây thư mục. Chưa có bằng chứng chạy thật là Antigravity đọc `references/` hay `assets/` (`not_run`); cần `examples/` hoặc `resources/` thì tạo thêm theo docs.

## Khác biệt so với Claude/Codex

- Không sao chép frontmatter `hooks` hoặc `${CLAUDE_SKILL_DIR}` từ Claude Code.
- Các sự kiện permission/tool approval tuân theo Antigravity runtime đang sử dụng; tên rule file không đủ làm security boundary.
- Rules cần load thường xuyên đặt ở `AGENTS.md` hoặc `.agents/rules/`; workflows reusable đặt trong Skills. Không duy trì song song workflow cũ và Skill cùng tên khi migrate.
- Với UI/IDE, vị trí cài global/plugin có thể khác CLI; kiểm tra docs theo surface và version.

## Vấn đề migration cần re-check

Tài liệu migration công khai từng hiển thị **thời hạn ngừng legacy workflows khác nhau** giữa host `antigravity.google` và `www.antigravity.google`. Repo này **không tuyên bố ngày deadline tuyệt đối**; phải xác minh lại documentation version, CLI/IDE version và thử migration trước khi tắt workflows cũ. Đọc: [Migration docs](https://www.antigravity.google/docs/migration/workflows-to-skills/).

## Smoke-test

1. Kiểm tra project `.agents/skills/` được indexed và tên Skill hiện diện.
2. Kiểm tra `AGENTS.md`/`GEMINI.md` đã được nhận diện, tránh nội dung trái ngược giữa 2 file.
3. Chạy positive và negative trigger test trong fresh session.
4. Chạy thử Skill với fixture synthetic, xác minh input/output và các bước QA.
5. Với action có side-effect, test permission deny và allow trong sandbox.
