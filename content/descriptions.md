# Cặp description tốt và xấu

> **Kết luận:** bảy lỗi `description` hay gặp nhất, mỗi lỗi một cặp Bad và Good. Mọi Good qua `validate` không có mã `DS*` và không có `VI4`; test `test_content_kit_counts` canh điều đó.

Cách dùng: đối chiếu `description` của skill mình với từng lỗi bên dưới. Quy tắc gốc ở [SKILL_AUTHORING_STANDARD.md](../standards/SKILL_AUTHORING_STANDARD.md) (`SK-00`, `SK-05`, `SK-14`). Nguồn `[nội bộ]` là quy ước của Studio, không phải yêu cầu của nhà cung cấp.

### Pair 1 — Mơ hồ, không nói làm gì và khi nào
- **Bad:** "Helps with documents."
- **Good:** "Extracts text and tables from PDF files and fills PDF forms. Use when the user mentions PDFs, forms or document extraction; not for Word or spreadsheets."
- **Why:** Agent chọn skill chỉ dựa vào `description`. Câu mơ hồ không nói skill làm gì, cho loại file nào, khi nào nên gọi, nên skill vừa bị gọi nhầm vừa bị bỏ sót. Nêu việc cụ thể, từ khoá người dùng hay nói, và một ranh giới `not for` (`SK-05`).
- **Source:** https://agentskills.io/specification — description phải nêu cả việc skill làm và khi nào dùng.

### Pair 2 — Viết ở ngôi thứ nhất
- **Bad:** "I can help you analyze Excel files. Use when you ask me to build pivot tables and charts."
- **Good:** "Analyzes Excel spreadsheets, builds pivot tables and charts. Use when the user works with .xlsx files or tabular data; not for cleaning CSV exports."
- **Why:** `description` được chèn vào system prompt của agent. Ngôi thứ nhất hoặc thứ hai làm câu mô tả lẫn với lời của người dùng và của agent, nên chọn skill kém chính xác. Dùng ngôi thứ ba, động từ chia ở hiện tại (`SK-05`, `DS2`).
- **Source:** https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Always write in third person".

### Pair 3 — Cụm kích hoạt chôn sau 600 ký tự
- **Bad:** "This skill was created by the data platform team to standardize how release candidates are checked across all squads. It encodes the checklist maintained in the engineering handbook, covers the three environments used for staging, and follows the review process agreed in the quarterly planning meeting. It replaces the earlier ad hoc scripts, keeps a history of previous versions in the repository, and is maintained by the platform guild together with the security group. The checklist has twelve items grouped by risk, from migrations and feature flags to rollback plans and on-call handover. Teams that adopt it report fewer surprises during release week. Use when the user asks to check a release candidate before deployment."
- **Good:** "Checks a release candidate against a twelve-item deployment checklist covering migrations, feature flags and rollback plans. Use when the user asks to review a release before deployment; not for writing release notes."
- **Why:** Claude Code cắt phần ghép của `description` và `when_to_use` ở 1 536 ký tự trong danh sách skill, nên điều cần để chọn skill phải nằm ở đầu. Studio đặt ngưỡng ~500 ký tự đầu cho cụm `Use when` (`DS4`); lịch sử và người bảo trì là thông tin cho thân `SKILL.md`, không cho `description`.
- **Source:** https://code.claude.com/docs/en/skills — "Put the key use case first"; mốc ~500 ký tự là của Studio `[nội bộ]` (`SK-05`).

### Pair 4 — Thiếu phạm vi âm nên trùng skill kề
- **Bad:** "Audits CSV data quality for missing fields, duplicate keys and invalid numbers. Use when the user mentions a CSV file."
- **Good:** "Audits CSV data quality for missing required fields, duplicate keys and invalid numeric values. Use when reviewing a CSV before import or reporting; not for converting, merging or reshaping CSV files."
- **Why:** Bad gọi skill cho mọi prompt có chữ CSV, kể cả "Convert this orders CSV to JSON" (ca near-miss `data-quality-audit-near-miss-convert` của SPR-18). Thêm `not for` nêu đúng việc kề dễ nhầm, rồi viết một ca eval `should_trigger: false` cho nó (`SK-05`, `SK-11`).
- **Source:** `[nội bộ]` `SK-05` và `SK-11`; ca near-miss ở `evals/data-quality-audit/cases.json`.

### Pair 5 — Chữ ép buộc thay cho điều kiện chọn
- **Bad:** "CRITICAL: You MUST use this skill whenever the user mentions databases. Use when any database comes up; ALWAYS call it first. NEVER answer without it."
- **Good:** "Reviews SQL migrations for locking and rollback risks. Use when the user shares a migration file or asks whether a schema change is safe; not for query tuning."
- **Why:** Model gần đây theo sát system prompt, nên chữ in hoa kiểu ép buộc làm skill bị gọi quá đà ở cả những prompt không liên quan. Nêu điều kiện bằng "Use when …" và thêm lý do khi cần nhấn mạnh (`SK-14`, `CT10`).
- **Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "The fix is to soften any aggressive language".

### Pair 6 — Quảng cáo thương hiệu thay vì điều kiện chọn
- **Bad:** "The world's best, award-winning toolkit from Acme Labs, trusted by thousands of teams. Use when you want amazing results."
- **Good:** "Generates an OpenAPI 3.1 spec from FastAPI route files. Use when the user asks for API documentation or a spec file; not for writing endpoint code."
- **Why:** Tên hãng và tính từ khen không giúp agent quyết định có gọi skill hay không. `description` chỉ nên trả lời hai câu hỏi: skill làm gì với đầu vào nào, và người dùng nói gì thì chọn nó (`SK-05`).
- **Source:** `[nội bộ]` `SK-05`; ý "mô tả việc và điều kiện dùng" đồng nhất với https://agentskills.io/specification.

### Pair 7 — Description thuần tiếng Việt
- **Bad:** "Soạn ghi chú phát hành từ các pull request đã gộp. Dùng khi người dùng cần viết ghi chú phát hành."
- **Good:** "Drafts release notes from merged pull requests. Use when the user asks for release notes; viết ghi chú phát hành."
- **Why:** Harness định tuyến skill bằng frontmatter, nên `description` viết bằng tiếng Anh với cụm `Use when`. Muốn bắt cả cách gọi tiếng Việt thì thêm một cụm Việt ngắn (tối đa 40 ký tự) vào cuối. Thân `SKILL.md` mới là nơi viết tiếng Việt; lint `VI4` canh việc này (`V13`).
- **Source:** `[nội bộ]` `SK-05` và `V13` ở [VIETNAMESE_SKILL_WRITING.md](../standards/VIETNAMESE_SKILL_WRITING.md).
