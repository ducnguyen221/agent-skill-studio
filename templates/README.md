---
title: "Templates"
status: active
updated: 2026-10-23
---
# Templates

Hai template là **scaffold** cho Skill mới, không phải Skill sản xuất. Lệnh `python3 studio.py new <name> ...` copy template, đổi `name`/`description` thành hợp lệ và để lại `STUDIO-DRAFT` để cảnh báo cần cá nhân hóa; `package` từ chối Skill còn dấu này.

| Template | Chọn bằng | Nội dung |
|---|---|---|
| `skill-template/SKILL.md` | mặc định (`--lang en`) | Một file 14 dòng không trống: frontmatter, mục đích, `## Gotchas`, `## References`. Chỉ `SKILL.md`, không thư mục con |
| `skill-template/SKILL.vi.md` | `--lang vi` | Cùng khung, thân tiếng Việt; frontmatter và nhãn mục giữ tiếng Anh. Viết theo [chuẩn tiếng Việt](../standards/VIETNAMESE_SKILL_WRITING.md) |
| `skill-template-full/` | `--full` | Bản đầy đủ, chỉ tiếng Anh (`--full --lang vi` thoát 2): `SKILL.md` + `references/PROCESS_TEMPLATE.md` (khuôn file process) + `scripts/` + `assets/` + `agents/openai.yaml` (chỉ Codex, xoá nếu không dùng) |

Trong bản đầy đủ:

- `references/`: phương pháp chuyên sâu, đọc theo nhu cầu; `PROCESS_TEMPLATE.md` là khuôn runbook (`Command:`, `Expect:`, `Stop if:`).
- `scripts/`: Python helper có thể chạy và bắt lỗi, không tự chạy khi chỉ load Skill.
- `assets/`: biểu mẫu, tài liệu, schema, dữ liệu synthetic dùng trực tiếp trong output.
- `agents/`: metadata riêng của host; `package` đưa thư mục này vào ZIP.

`evals/` chủ đích **không nằm trong template skill runtime**. Lệnh `new` tạo `evals/<name>/cases.json` riêng, rỗng có chủ đích. Phải viết 3 test thật mới đủ điều kiện release.

Cả hai template được đồng bộ sang `skills/skill-creator-studio/assets/skill-template/` và `assets/skill-template-full/` để Skill factory chạy độc lập ngoài repo. Sau khi sửa template gốc, chạy `python3 studio.py sync-template`, rồi `python3 studio.py sync-template --check` (so từng file hai chiều; file thừa ở bản sao cũng là lệch).
