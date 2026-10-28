---
title: "Standards Directory"
status: active
updated: 2026-10-28
---
# Standards Directory

Các quy tắc ở đây áp dụng **khi tạo và quản lý** Skills, không mặc định được chèn toàn bộ vào context một phiên agent. Tám file; đọc theo mục tiêu, bắt đầu từ file lõi.

## Đọc gì khi nào

| Khi bạn… | Đọc |
|---|---|
| viết, kiểm hay sửa một skill (luật `SK-00`…`SK-15`, mức MUST/SHOULD, thứ tự ưu tiên, vòng đời) | `SKILL_AUTHORING_STANDARD.md` — file lõi, đọc đầu tiên |
| viết một skill có thân tiếng Việt (14 quy tắc, lint `VI1`–`VI5`) | `VIETNAMESE_SKILL_WRITING.md` |
| soạn skill, workflow hay file luật agent và cần biết loại nào có luật gì | `DOC_TYPES.md` |
| cài hay kiểm skill trên Claude Code, Codex hoặc Antigravity; cần đường cài, giới hạn, cách nạp `AGENTS.md` | `HARNESSES.md` |
| đo một skill bằng model thật, ghi khối `evaluated`, hiểu `not_run` | `EVALUATION_STANDARD.md` |
| skill có side effect, hook, secret; cần threat model | `SECURITY_AND_PERMISSIONS.md` |
| muốn biết một luật đến từ nguồn nào, hay map 46 check cộng đồng vào luật Studio | `SOURCE_TRACEABILITY.md` |
| cần ví dụ để chép và sửa | [`../examples/README.md`](../examples/README.md): mẫu `description`, case eval, hai skill mẫu; nằm ngoài `standards/` và `skills/`, không vào gói phát hành |

Không đồng nhất rule nội bộ với normative requirement trong tài liệu chính thức. Với claims current, xác minh lại release docs theo thời gian.

## Hệ sinh thái

Studio là xưởng chuẩn hoá skill của OpcOS: cấp chuẩn viết, kiểm định và đóng gói Agent Skills (quy trình NEW / AUDIT / REFINE, `studio.py validate`, bộ evals ngoại vi) cho các plugin khác. `system/registry.json` của OpcOS xếp nó vào nhóm `engineering`, loại plugin, tuỳ chọn cài.

- **Bàn giao vào:** `production-brief.md` có `Target Studio` là repo này; mục `Technical Specs` thêm khối Skill Spec 7 trường: Mode (NEW/AUDIT/REFINE) · Target · Owner Team/Studio · Triggers (ít nhất 3 câu kích hoạt đúng + 1 câu không) · Harness Targets · Side Effects & Permissions · Evidence (bắt buộc với REFINE).
- **Bàn giao ra:** báo cáo AUDIT (ERROR/WARN/INFO) hoặc diff cùng kết quả `studio.py validate --all --require-evals` và eval; eval chưa chạy thì theo [Không pass giả](EVALUATION_STANDARD.md#không-pass-giả-not_run). Repo sở hữu skill tự cài và tự phát hành; Studio không sửa trực tiếp vào repo đó.
