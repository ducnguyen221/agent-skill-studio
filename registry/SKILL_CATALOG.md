# Skill Catalog — Inventory và ownership

| Name | Purpose | Supported target paths | Evaluation | Status |
|---|---|---|---|---|
| `skill-creator-studio` | NEW/AUDIT/REFINE portable Skills | Claude `.claude/skills` / Codex+AGY `.agents/skills` | 8 cases (5 nên kích hoạt, 3 không); mô hình đã chạy 18/10 trên Claude Code và Codex, Antigravity `not_run` | Prototype |
| `data-quality-audit` | CSV schema/key/null/numeric check | Tương tự | 8 cases (5 nên kích hoạt, 3 không); mô hình đã chạy 18/10 trên Claude Code và Codex, Antigravity `not_run` | Prototype |

`model_evaluated=false` cho cả hai Skill. SPR-18 đã chạy mô hình ngày 18/10 (số đo và giới hạn: `system/docs/plans/2026-10-17-skill-studio-eval/REPORT.md`); chưa đạt điều kiện bật: tiêu chí cần ≥ 3 cặp A/B bên có Skill hơn, đo được 0 cặp hơn ở cả hai harness; riêng data-quality-audit trên Codex có 2/3 ca không-nên-kích-hoạt vẫn kích hoạt. Đây là số đo trên mẫu nhỏ, không kết luận Skill tốt hay kém. Cổng bật là test `test_model_evaluated_requires_counted_evidence` (đếm lại từ log). `model-evaluated` ≠ Production (`standards/EVALUATION_STANDARD.md`, mục Release gate nội bộ).

Thông tin máy đọc: [catalog.json](catalog.json). Trước production phải cập nhật owner, version, run logs và trạng thái. Nếu có Skill mới, kiểm tra tên/trigger trùng, bổ sung entry và chạy tests.

## Governance

- Không đưa API keys, private customer examples hoặc session secrets vào registry.
- Có owner chịu trách nhiệm, review date, supported runtime và audit trail cho mỗi Skill.
- Nếu đổi `description`, kiểm tra tác động đến các trigger của Skill khác; tránh hai Skill tranh một nhiệm vụ.
- Status `prototype-static-validated` không có nghĩa đã chạy eval với Claude/Codex/AGY.
