# OpenAI Codex Adapter — Cấu hình riêng cho Codex

Checked: 2026-10-23 · nguồn đã mở lại: [Build Skills](https://learn.chatgpt.com/docs/build-skills) (đích cài, `agents/openai.yaml`, giới hạn danh sách). [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md): `not_run:chưa mở lại` ở lần này. Phiên bản Codex trên máy chạy kiểm: `codex-cli 0.163.0`.

## Discovery

- Repo/project: `.agents/skills/<skill-name>/SKILL.md` ở thư mục làm việc và mỗi thư mục cha tới gốc repo.
- User scope: `~/.agents/skills/<skill-name>/SKILL.md`. Docs còn nêu skill quản trị `/etc/codex/skills` và skill hệ thống đi kèm Codex (Studio không cài vào đó). Studio: `install --agent codex --user` chép vào `~/.agents/skills/<tên>`, và `~/.agents` phải có sẵn (thiếu thì thoát 2, không tạo gì).
- Skills được chọn bởi explicit/implicit invocation; trong Codex có `$skill-name`, `/skills` theo hỗ trợ hiện hành.
- Repo instructions: `AGENTS.md` / `AGENTS.override.md`; Codex đọc theo đường repo root → current working directory, file gần CWD có thể ghi đè chỉ dẫn cấp trên, dưới giới hạn budget.

## Cài

```bash
mkdir -p ./target-project   # --workspace phải là thư mục có sẵn, thiếu thì thoát 2
python3 studio.py install skills/skill-creator-studio --agent codex --workspace ./target-project
# cấp người dùng
python3 studio.py install skills/skill-creator-studio --agent codex --user
# Rồi trong Codex: $skill-creator-studio hoặc liệt kê /skills
```

Codex và Antigravity cùng dùng `.agents/skills/` trong project. Không copy cùng skill hai lần thành tên khác nhau vì chúng sẽ cạnh tranh trigger.

## Giới hạn danh sách skill

- Docs: danh sách skill nạp ban đầu dùng tối đa 2 % cửa sổ ngữ cảnh của model, hoặc 8 000 ký tự khi chưa biết cỡ cửa sổ; chỉnh được bằng `skills.max_context_tokens`, trần 10 000 token.
- `[codex 0.147, mã]`: mỗi `description` 1 024 ký tự, thân `SKILL.md` 8 000 byte (Studio báo `ST3` WARN khi thân vượt). Máy này đang chạy `codex-cli 0.163.0`, khác 0.147: **chưa đọc lại mã** ở 0.163.0, hai con số này chưa xác nhận cho bản đó.

## Cấu trúc Skill

- Portable manifest (`name`, `description` và optional fields theo Agent Skills) được ưu tiên.
- `agents/openai.yaml` là file tùy chọn cung cấp **UI metadata, invocation policy, dependency information** cho ChatGPT/Codex. Nó không phải chuẩn bắt buộc và chỉ thêm khi dự án thực sự cần. Template đầy đủ (`new --full`) có mẫu `agents/openai.yaml` ghi rõ "Optional, Codex only; delete if unused".
- Không áp dụng Claude Code `hooks` YAML vào Codex. Sandbox/approvals và tính năng policy cần cấu hình riêng theo Codex version và product surface.

## Tool and permission controls

- `SKILL.md` mô tả target/action/validation, không có quyền tự cấp authorization.
- Scripts cần chạy với cwd/path đúng. Đừng copy absolute path ở máy tác giả.
- Destructive/publishing tasks cần một action plan, reviewer và permissions tương ứng; không dựa vào việc model hứa tuân thủ.

## Smoke-test

1. Chạy agent từ repo root, xác nhận `AGENTS.md` đọc đúng, không bị local override.
2. Dùng `/skills` hoặc `$skill-creator-studio`, kiểm tra explicit invocation.
3. Chạy positive/negative trigger prompts và chấm output.
4. Test packaging không mang `evals/` theo khi chuyển sang khác runtime.
5. Kiểm tra lại chính sách sandbox/approvals trước mỗi automated deployment.

**Không nhầm lẫn:** Skill package dùng `SKILL.md`, còn `AGENTS.md` là persistent project instructions. Hai thứ phục vụ mục tiêu khác nhau.
