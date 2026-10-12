# Templates

`skill-template/` là **scaffold** cho Skill mới, không phải Skill sản xuất. Lệnh `python3 studio.py new <name> ...` sẽ copy và đổi `name`/`description` thành hợp lệ nhưng để lại `STUDIO-DRAFT` để cảnh báo cần cá nhân hóa.

- `SKILL.md`: entrypoint + route.
- `references/`: phương pháp chuyên sâu, đọc theo nhu cầu.
- `scripts/`: Python helper có thể chạy và bắt lỗi, không tự chạy khi chỉ load Skill.
- `assets/`: biểu mẫu, tài liệu, schema, dữ liệu synthetic dùng trực tiếp trong output.

`evals/` chủ đích **không nằm trong template skill runtime**. Lệnh `new` tạo `evals/<name>/cases.json` riêng, rỗng có chủ đích. Phải viết 3 test thật mới đủ điều kiện release.

Template được đồng bộ sang `skills/skill-creator-studio/assets/skill-template/` để Skill factory chạy độc lập ngoài repo. Sau khi sửa template gốc, chạy `python3 studio.py sync-template`, rồi `python3 studio.py sync-template --check`.
