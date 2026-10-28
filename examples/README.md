---
title: "Bộ ví dụ mẫu"
status: active
updated: 2026-10-23
---
# Bộ ví dụ mẫu

> **Kết luận:** thư mục này chứa ví dụ để chép và sửa khi viết skill: bảy cặp `description` tốt và xấu, ba case eval, hai skill mẫu ngắn và skill CSV `data-quality-audit` (có script thật, kèm bộ eval ở `evals/data-quality-audit/`). Thư mục nằm ngoài `skills/` nên không bao giờ vào gói phát hành.

Mỗi mục trích nguồn chính thức (URL) hoặc gắn `[nội bộ]` khi là quy ước của Studio. Chưa có mục nào được chạy trên model thật (`not_run`).

| File | Đọc khi |
|---|---|
| [descriptions.md](descriptions.md) | viết hoặc sửa `description`; skill bị gọi nhầm hoặc không được gọi |
| [eval-cases.md](eval-cases.md) | lập `evals/<skill>/cases.json`; cần ví dụ case typical, edge, near-miss và bản xuất agentskills |
| [exemplar/writing-commit-messages/SKILL.md](exemplar/writing-commit-messages/SKILL.md) | cần khuôn skill tiếng Anh ngắn, có `## Gotchas`, tên dạng gerund |
| [exemplar-vi/writing-release-notes/SKILL.md](exemplar-vi/writing-release-notes/SKILL.md) | cần khuôn skill thân tiếng Việt, frontmatter tiếng Anh |

Quy tắc nền: [SKILL_AUTHORING_STANDARD.md](../standards/SKILL_AUTHORING_STANDARD.md) cho mọi skill, [VIETNAMESE_SKILL_WRITING.md](../standards/VIETNAMESE_SKILL_WRITING.md) cho thân tiếng Việt.

Kiểm hai skill mẫu: `python studio.py validate examples/exemplar/writing-commit-messages` và `python studio.py validate examples/exemplar-vi/writing-release-notes`; mỗi lệnh phải báo 0 errors, 0 warnings. Test `tests/test_content.py` canh cả bộ.
