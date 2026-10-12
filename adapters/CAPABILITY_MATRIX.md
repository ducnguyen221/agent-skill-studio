# Capability Matrix — Skill Studio

**As-of 2026-10-12.** "Supported" nghĩa là đã tìm thấy tài liệu công khai tương ứng, không nghĩa là đã tự chạy thử các runtime trong môi trường này.

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

**Quyết định:** Canonical Skill trong `skills/`, adapter config bên ngoài hoặc generated; command `studio.py install` copy vào nơi agent có discovery. Đừng giả định symlink/permissions từ agent A tự hoạt động trên agent B.

Sources: [Claude](https://code.claude.com/docs/en/skills) / [Codex](https://learn.chatgpt.com/docs/build-skills) / [Antigravity](https://www.antigravity.google/docs/skills).
