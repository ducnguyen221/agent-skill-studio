# Skill Catalog — Inventory và ownership

| Name | Purpose | Supported target paths | Evaluation | Status |
|---|---|---|---|---|
| `skill-creator-studio` | NEW/AUDIT/REFINE portable Skills | Claude `.claude/skills` / Codex+AGY `.agents/skills` | 4 cases schema-ready, **model not run** | Prototype |
| `data-quality-audit` | CSV schema/key/null/numeric check | Tương tự | 4 cases schema-ready, **model not run** | Prototype |

Thông tin máy đọc: [catalog.json](catalog.json). Trước production phải cập nhật owner, version, run logs và trạng thái. Nếu có Skill mới, kiểm tra tên/trigger trùng, bổ sung entry và chạy tests.

## Governance

- Không đưa API keys, private customer examples hoặc session secrets vào registry.
- Có owner chịu trách nhiệm, review date, supported runtime và audit trail cho mỗi Skill.
- Nếu đổi `description`, kiểm tra tác động đến các trigger của Skill khác; tránh hai Skill tranh một nhiệm vụ.
- Status `prototype-static-validated` không có nghĩa đã chạy eval với Claude/Codex/AGY.
