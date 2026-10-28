# Capability Matrix — Skill Studio

Checked: 2026-10-23 · nguồn mở lại: [Claude](https://code.claude.com/docs/en/skills), [Codex](https://learn.chatgpt.com/docs/build-skills), [Antigravity](https://antigravity.google/docs/skills). "Supported" nghĩa là đã tìm thấy tài liệu công khai tương ứng, không nghĩa là đã tự chạy thử runtime trong môi trường này.

| Khả năng | Claude Code | OpenAI Codex | Google Antigravity |
|---|---|---|---|
| `SKILL.md` theo Agent Skills | Supported | Supported | Supported |
| Project skill path | `.claude/skills/` | `.agents/skills/` | `.agents/skills/` |
| Global skill path | `~/.claude/skills/` | `~/.agents/skills/` | `~/.gemini/config/skills/` |
| Repo instruction | `CLAUDE.md` (`@AGENTS.md` import) | `AGENTS.md`, `.override` | `AGENTS.md`, `GEMINI.md` và rules |
| Vendor-specific skill hooks in frontmatter | Claude-supported | **Không tương đương** | **Không tương đương** |
| Custom skill UI metadata | Claude extensions | `agents/openai.yaml` optional | Theo UI/runtime của AGY |
| Implicit activation by description | Supported | Supported | Supported |
| Manual invocation | `/skill-name` | `$skill-name`, `/skills` | Theo IDE/CLI, thường `/skill-name` |
| Storage của evals | Studio đặt ngoài | Studio đặt ngoài | Studio đặt ngoài |
| Portable six-key YAML frontmatter | Supported | Compatible | Compatible core, verify target version |
| Fresh-session model eval | Cần agent runtime | Cần agent runtime | Cần agent runtime |
| `studio.py install --workspace` | `.claude/skills/<tên>` | `.agents/skills/<tên>` | `.agents/skills/<tên>` |
| `studio.py install --user` | **Không hỗ trợ** (thoát 2) | `~/.agents/skills/<tên>`; `~/.agents` phải có sẵn | `~/.gemini/config/skills/<tên>` (App/IDE); `~/.gemini/config` phải có sẵn; CLI dùng đích khác |
| Khoá frontmatter ngoài sáu khoá portable | 14 khoá, chỉ qua `validate --target claude-code` (`FM6` WARN) | Không; metadata riêng ở `agents/openai.yaml` (tuỳ chọn) | Không có trong docs đã đọc |
| Thư mục con trong docs | Không đọc lại ở lần này | `agents/openai.yaml` (tuỳ chọn); phần còn lại không đọc lại ở lần này | `scripts/` `examples/` `resources/`; Studio giữ thêm `references/` `assets/`, chưa chạy thật |
| Giới hạn danh sách skill | `description` + `when_to_use` cắt ở 1 536 ký tự | ≤2 % ngữ cảnh / 8 000 ký tự; `[codex 0.147, mã]` 1 024 ký tự / 8 000 B (máy này 0.163.0, chưa đọc lại mã) | Không thấy số trong docs đã đọc |

**Quyết định:** Canonical Skill trong `skills/`, adapter config bên ngoài hoặc generated; command `studio.py install` copy vào nơi agent có discovery. Đừng giả định symlink/permissions từ agent A tự hoạt động trên agent B.

Sources (mở lại 2026-10-23): [Claude](https://code.claude.com/docs/en/skills) / [Codex](https://learn.chatgpt.com/docs/build-skills) / [Antigravity](https://antigravity.google/docs/skills). Gọi Codex hoặc Antigravity thật: `not_run:needs-directive`.
