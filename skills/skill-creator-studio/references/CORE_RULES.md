---
title: "Core Rules (SK-00…SK-15)"
status: generated
updated: 2026-10-28
---
# Core Rules

> Generated from standards/SKILL_AUTHORING_STANDARD.md — do not edit. Full wording and the other standards live in the Studio repo; regenerate with `python tests/gen_core_rules.py`.

## Rules

### SK-00 — Manifest portable [MUST] · kiểm: `FM1`, `FM2`, `FM4`–`FM6`, `DS1`
`SKILL.md` mở bằng frontmatter ở dòng 1 với `name` và `description`.

### SK-01 — Progressive disclosure [SHOULD] · kiểm: `ST1`, `ST2`
Thân `SKILL.md` là bộ định tuyến, <500 dòng, <5 000 token.

### SK-02 — Content lists và cắt gọn [SHOULD] · kiểm: review
Mục lục theo `SK-15`.

### SK-03 — Mức tự do theo rủi ro [MUST khi thiết kế] · kiểm: review
Tự do cao thì văn xuôi, vừa thì mẫu ưu tiên, thấp (rủi ro: thanh toán, xoá, deploy, migration) thì script/schema/approval.

### SK-04 — Thử trên model đích [SHOULD; MUST nếu production] · kiểm: review
Không xoá rule theo trực giác: chạy ≥3 tình huống thật, bật/tắt skill, trên model đích (ghim `--model`), so A/B ở phiên mới, chỉ xoá khi không kém.

### SK-05 — Ngắn và dễ kích hoạt [SHOULD] · kiểm: `DS2`–`DS5`, `FM8`
Mỗi skill một nhóm việc.

### SK-06 — Workflow kiểm được [MUST nếu nhiều bước] · kiểm: review
Nêu từng bước, `Done when`, đường quay lại khi kiểm lỗi; việc phức tạp dùng plan-validate-execute.

### SK-07 — Vòng phản hồi [MUST nếu quan trọng] · kiểm: review
Validate, chẩn đoán, sửa, validate lại; giới hạn số lần, báo blocker thay vì lặp vô hạn.

### SK-08 — Template, ví dụ, nhánh [SHOULD] · kiểm: review
Ghi mẫu là **Strict** (schema/API/CSV) hay **Flexible** (memo/báo cáo).

### SK-09 — Chạy được ở máy khác [MUST nếu có dependency] · kiểm: `ST6`, `SC3`, `SEC`
Ghi tool, phiên bản, cách cài, fallback; đường dẫn tương đối, dùng `/`, không cứng `C:\Users\...`, không secret; asset nằm trong skill; nói rõ script để *chạy* hay *đọc*.

### SK-10 — Cổng thật cho điều bắt buộc [MUST nếu rủi ro] · kiểm: review
Lời nhắc có thể bị bỏ qua hoặc bị compact.

### SK-11 — Eval trước [SHOULD; MUST nếu production] · kiểm: `EV1`–`EV6`
Trước khi mở rộng: ≥3 prompt thực, một negative trigger, baseline không-skill.

### SK-12 — Quy tắc quan trọng lên đầu [SHOULD] · kiểm: review
Sau compaction Claude Code chỉ giữ 5 000 token đầu mỗi skill, tổng 25 000.

### SK-13 — Không bắt chép suy luận [MUST] · kiểm: `NM2`
Bắt agent xuất chain-of-thought nội bộ có thể bị từ chối (loại `reasoning_extraction`).

### SK-14 — Chữ ép buộc phải có lý do [SHOULD] · kiểm: `CT10` (WARN)
`MUST`/`NEVER`/`ALWAYS`/`CRITICAL` đứng trơ làm model gần đây phản ứng quá đà: kèm lý do ("vì…") hoặc viết "Use … when …".

### SK-15 — Contents và điều giữ ở đầu [SHOULD] · kiểm: `ST5`/`ST7`
Reference >100 dòng phải có `## Contents`; thân >100 dòng nên có.
