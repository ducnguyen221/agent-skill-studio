---
title: "Templates"
status: active
updated: 2026-10-23
---
# Templates

Hai template (`skill-template/` và `skill-template-full/`, nằm ở `skills/skill-creator-studio/assets/`, bản duy nhất) là **scaffold** cho Skill mới, không phải Skill sản xuất. Lệnh `python3 studio.py new <name> ...` copy template, đổi `name`/`description` thành hợp lệ và để lại `STUDIO-DRAFT` để cảnh báo cần cá nhân hóa; `package` từ chối Skill còn dấu này.

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

`starter-project/` là mẫu **cho dự án khác** (không phải skill): `AGENTS.md` là bộ luật chung duy nhất; `CLAUDE.md` nạp nó bằng `@AGENTS.md`, Codex đọc thẳng `AGENTS.md`, `GEMINI.md` trỏ về `AGENTS.md`; mỗi file có dòng `install` đúng cờ của engine. Xem [README của mẫu](starter-project/README.md).

Kiểm trình bày sau khi sửa tài liệu này: `python3 studio.py fmt --check templates/README.md`. Hai template chỉ có một bản, ở `skills/skill-creator-studio/assets/skill-template/` và `assets/skill-template-full/`; lệnh `new` luôn lấy từ đó, trong hay ngoài repo, nên không còn bản sao để đồng bộ. Sửa template thì sửa thẳng ở đó.
