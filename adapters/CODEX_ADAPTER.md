# OpenAI Codex Adapter — Cấu hình riêng cho Codex

**Checked:** 2026-10-12 · [Build Skills](https://learn.chatgpt.com/docs/build-skills) · [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Discovery

- Repo/project: `.agents/skills/<skill-name>/SKILL.md`.
- User scope: `~/.agents/skills/<skill-name>/SKILL.md` theo tài liệu hiện hành.
- Skills được chọn bởi explicit/implicit invocation; trong Codex có `$skill-name`, `/skills` theo hỗ trợ hiện hành.
- Repo instructions: `AGENTS.md` / `AGENTS.override.md`; Codex đọc theo đường repo root → current working directory, file gần CWD có thể ghi đè chỉ dẫn cấp trên, dưới giới hạn budget.

## Cài

```bash
python3 studio.py install skills/skill-creator-studio --agent codex --workspace .
# Rồi trong Codex: $skill-creator-studio hoặc liệt kê /skills
```

Codex và Antigravity cùng dùng `.agents/skills/` trong project. Không copy cùng skill hai lần thành tên khác nhau vì chúng sẽ cạnh tranh trigger.

## Cấu trúc Skill

- Portable manifest (`name`, `description` và optional fields theo Agent Skills) được ưu tiên.
- `agents/openai.yaml` là file tùy chọn cung cấp **UI metadata, invocation policy, dependency information** cho ChatGPT/Codex. Nó không phải chuẩn bắt buộc và chỉ thêm khi dự án thực sự cần.
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
