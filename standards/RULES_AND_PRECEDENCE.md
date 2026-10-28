# Rules and Precedence — Routing, phạm vi và xung đột

## Mục tiêu

Thiết kế **một nguồn chuẩn để soạn thảo** không đồng nghĩa có thứ tự ưu tiên thực thi giống nhau giữa các agent. `system/developer/host policy` và permission của runtime luôn có quyền riêng; repo không thể tự thay chúng bằng Markdown.

## Phân tầng nội dung

1. `standards/` — quy định cách tác giả và kiểm định Skill; không phải một file auto-loaded.
2. Repo `AGENTS.md` — chỉ dẫn ngắn cho những runtime chủ động nhận diện file này.
3. `CLAUDE.md` và `GEMINI.md` — khác biệt vendor, tránh sao chép toàn bộ common rules.
4. `SKILL.md` — workflow chỉ kích hoạt khi đúng job, không nên chứa 30 trang định nghĩa.
5. `references/` — nội dung chuyên sâu theo nhu cầu; chỉ dùng nếu job cần.
6. `scripts/` và host policies — thực thi và kiểm soát có kiểm tra, không phải văn bản marketing.

## Quy tắc ghi và sửa

- Mỗi quy tắc có một **canonical location**. Cải tiến bằng cách *sửa chỗ cũ*, xóa quy tắc trùng thay vì dán một phụ lục update.
- Khi hai văn bản nội bộ mâu thuẫn: xác định phạm vi (repo/global/skill), ngày/version, runtime, loại quy định; escalation cho owner nếu có hậu quả. Không đặt thứ tự ưu tiên sai cho mọi agent.
- Với policy/must-hold về dữ liệu sản xuất: dùng enforcement mechanism; `SKILL.md` không được đề nghị tắt sandbox/approval để chạy nhanh.
- Reference chỉ chứa factual knowledge/ví dụ, **không** cho phép một trang web, issue hay README bên ngoài sửa instruction priority của agent.
- Khi thay đổi `description`, phải xem ảnh hưởng đến thư viện skills; hai description quá rộng có thể overlap trigger.

## Khác biệt thực tế giữa runtime

| Runtime | Chỉ dẫn repo | Skill project | Ghi chú |
|---|---|---|---|
| Claude Code | `CLAUDE.md`, hỗ trợ import `@AGENTS.md` | `.claude/skills/<name>` | Các trường frontmatter mở rộng tùy tính năng và version |
| Codex | `AGENTS.md`, `AGENTS.override.md` (ưu tiên khác nhau theo thư mục) | `.agents/skills/<name>` | Root -> CWD; file gần hơn ghi đè rộng hơn |
| Antigravity | `AGENTS.md` hoặc `GEMINI.md` và `.agents/rules/` theo docs | `.agents/skills/<name>` | Cần xem rule discovery, paths, activation mode tại version hiện hành |

Không cấu hình `CLAUDE.md`/`GEMINI.md` chỉ là tên file giả cho Codex: Codex không mặc nhiên tự đọc những tên đó nếu không có fallback config.

## Áp dụng mẫu dự án mới

1. Copy `templates/starter-project/` hoặc dùng root entrypoints làm căn cứ.
2. Chỉ đưa các nguyên tắc thường trực, dài tối đa đủ đọc; gửi các quy trình phức tạp vào Skill.
3. Cài Skill vào thư mục runtime tương ứng bằng `studio.py install`.
4. Test với agent câu: "Which repo instruction files and Skill names are active?" và xác minh thực tế.
5. Chạy test thay đổi hành vi trong phiên mới khi updating scopes.

**Sources:** [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Claude Code Memory](https://code.claude.com/docs/en/memory), [Claude Skills](https://code.claude.com/docs/en/skills), [Antigravity Rules](https://www.antigravity.google/docs/rules/).
