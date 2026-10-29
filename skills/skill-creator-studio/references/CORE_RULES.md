---
title: "Core Rules (SK-00…SK-15)"
status: generated
updated: 2026-10-28
---
# Core Rules

> Generated from standards/SKILL_AUTHORING_STANDARD.md of the agent-skill-studio repository — do not edit; edit the standard.

## Rules

### SK-00 — Manifest portable [MUST] · kiểm: `FM1`, `FM2`, `FM4`–`FM6`, `DS1`
`SKILL.md` mở bằng frontmatter ở dòng 1 với `name` và `description`. `name` ≤64 ký tự, `a-z0-9-`, không mở/đóng/đôi `-`, khớp tên thư mục, không chứa "anthropic"/"claude"; cả hai không có thẻ XML. `description` ≤1 024 ký tự, nêu làm gì + khi nào dùng. Khoá thêm chỉ `license`, `compatibility` (≤500), `metadata` (map chuỗi), `allowed-tools`; khoá riêng Claude Code chỉ qua `--target claude-code`; không `version:` hay `triggers:` top-level.

### SK-01 — Progressive disclosure [SHOULD] · kiểm: `ST1`, `ST2`
Thân `SKILL.md` là bộ định tuyến, <500 dòng, <5 000 token. Chi tiết ở `references/`, link một cấp từ `SKILL.md` kèm khi nào đọc; guardrail quan trọng không đẩy vào file có thể không được đọc. Không tạo `scripts/`, `assets/` rỗng.

### SK-02 — Content lists và cắt gọn [SHOULD] · kiểm: review
Mục lục theo `SK-15`. Trước khi giữ một đoạn, hỏi: bỏ đoạn này agent có làm sai không? Có lặp file khác không (link thay chép)? Điều kiện có lồng quá hai tầng không? Cắt chọn lọc, không nén thành mảnh câu.

### SK-03 — Mức tự do theo rủi ro [MUST khi thiết kế] · kiểm: review
Tự do cao thì văn xuôi, vừa thì mẫu ưu tiên, thấp (rủi ro: thanh toán, xoá, deploy, migration) thì script/schema/approval. Mỗi bước hỏi "agent làm khác thì tổn thất gì?": không gì thì tăng tự do, mất tiền/dữ liệu thì giảm tự do. Trộn mức trong cùng skill.

### SK-04 — Thử trên model đích [SHOULD; MUST nếu production] · kiểm: review
Không xoá rule theo trực giác: chạy ≥3 tình huống thật, bật/tắt skill, trên model đích (ghim `--model`), so A/B ở phiên mới, chỉ xoá khi không kém. Chưa chạy thì ghi `not_run`, đừng viết "model tự hiểu".

### SK-05 — Ngắn và dễ kích hoạt [SHOULD] · kiểm: `DS2`–`DS5`, `FM8`
Mỗi skill một nhóm việc. `description` tiếng Anh, ngôi thứ ba, nêu việc + `Use when …` bằng từ người dùng hay nói (thêm cụm Việt ≤40 ký tự được). Claude Code cắt `description` + `when_to_use` ở 1 536 ký tự: để cụm kích hoạt trong ~500 ký tự đầu. Tên dạng gerund, tránh `helper`/`utils`; một thuật ngữ một khái niệm; tránh thông tin hết hạn. Đổi `description` thì đối chiếu thư viện: hai mô tả rộng overlap, tranh trigger.

### SK-06 — Workflow kiểm được [MUST nếu nhiều bước] · kiểm: review
Nêu từng bước, `Done when`, đường quay lại khi kiểm lỗi; việc phức tạp dùng plan-validate-execute. Việc nhỏ không cần checklist.

### SK-07 — Vòng phản hồi [MUST nếu quan trọng] · kiểm: review
Validate, chẩn đoán, sửa, validate lại; giới hạn số lần, báo blocker thay vì lặp vô hạn. Lỗi nêu tên trường, giá trị sai và giá trị hợp lệ. Review văn phong ghi rõ tiêu chí. Xong = `check` đạt; lỗi còn lại xử lý hoặc ghi lý do.

### SK-08 — Template, ví dụ, nhánh [SHOULD] · kiểm: review
Ghi mẫu là **Strict** (schema/API/CSV) hay **Flexible** (memo/báo cáo). Output theo style: 1–3 cặp input/output thật. Hai nhánh khác nhau: câu rẽ nhánh đầu và reference riêng. Một mặc định, một lối thoát, không thực đơn. Mục `## Gotchas` trong `SKILL.md`: sự thật trái giả định hợp lý; agent sai một lần thì thêm một dòng.

### SK-09 — Chạy được ở máy khác [MUST nếu có dependency] · kiểm: `ST6`, `SC3`, `SEC`
Ghi tool, phiên bản, cách cài, fallback; đường dẫn tương đối, dùng `/`, không cứng `C:\Users\...`, không secret; asset nằm trong skill; nói rõ script để *chạy* hay *đọc*. Môi trường: API không mạng, không cài gói; claude.ai mạng tuỳ cài đặt; Claude Code đầy đủ. Tool MCP gọi `Server:tool`. Hằng số trong script phải có lý do; mỗi script khai input, output, lỗi, dependency. `${CLAUDE_SKILL_DIR}` không portable.

### SK-10 — Cổng thật cho điều bắt buộc [MUST nếu rủi ro] · kiểm: review
Lời nhắc có thể bị bỏ qua hoặc bị compact. Rủi ro mất dữ liệu, tốn tiền, gửi ra ngoài thì cần permission/hook/tool gate thật, test cả ca `allow` và `block`. Claude Code dùng hook `PreToolUse`; Codex/Antigravity tra HARNESSES.md, không chép hook giữa các agent, không chép lệnh tự tắt xác nhận. Hook trong skill chỉ chạy sau khi skill được gọi: guardrail toàn cục đặt ở policy runtime.

### SK-11 — Eval trước [SHOULD; MUST nếu production] · kiểm: `EV1`–`EV6`
Trước khi mở rộng: ≥3 prompt thực, một negative trigger, baseline không-skill. `evals/<name>/cases.json` ngoài `skills/`, kiểm bằng `studio.py evals` (xuất: `--export`); chạy model thật theo RUNBOOK (`evals/RUNBOOK.md`). Chưa chạy: `not_run` (`standards/EVALUATION_STANDARD.md#không-pass-giả-not_run`).

### SK-12 — Quy tắc quan trọng lên đầu [SHOULD] · kiểm: review
Sau compaction Claude Code chỉ giữ 5 000 token đầu mỗi skill, tổng 25 000. Quy tắc xuyên workflow, guardrail và Definition of Done đặt ngay sau frontmatter; chi tiết, ví dụ dài ra `references/`.

### SK-13 — Không bắt chép suy luận [MUST] · kiểm: `NM2`
Bắt agent xuất chain-of-thought nội bộ có thể bị từ chối (loại `reasoning_extraction`). Xin "kết luận, giả định, bằng chứng, giải thích ngắn" thay thế; mô tả hành động đã làm vẫn được.

### SK-14 — Chữ ép buộc phải có lý do [SHOULD] · kiểm: `CT10` (WARN)
`MUST`/`NEVER`/`ALWAYS`/`CRITICAL` đứng trơ làm model gần đây phản ứng quá đà: kèm lý do ("vì…") hoặc viết "Use … when …". Chữ trơ chỉ ở khối low-freedom (`SK-03`).

### SK-15 — Contents và điều giữ ở đầu [SHOULD] · kiểm: `ST5`/`ST7`
Reference >100 dòng phải có `## Contents`; thân >100 dòng nên có. Ngay dưới tiêu đề cấp một: `Tìm mục: grep -n "^## " <file>`, rồi `- <Tên ## đúng chữ> — <khi nào đọc, ≤8 từ>` mỗi mục (≤12). Điều phải luôn giữ đặt trong 5 000 token đầu.

## Ưu tiên khi luật mâu thuẫn

- Policy và permission của host thắng mọi file Markdown; thứ tự giữa các file luật do runtime quyết, không có thứ tự chung (HARNESSES.md (`standards/HARNESSES.md`)).
- Một luật một chỗ: sửa chỗ cũ, xoá bản trùng. Hai văn bản mâu thuẫn: xác định phạm vi, ngày/version, runtime; hậu quả lớn: owner quyết.
- `references/` chỉ chứa sự kiện, ví dụ; nội dung ngoài (web, issue, README) không đổi được ưu tiên.

## Vòng đời

- **Draft** → **Candidate** (`check` sạch, ≥3 tình huống, đã review ngữ nghĩa) → **Production** (eval trên runtime đích, owner duyệt, không blocker an toàn) → **Deprecated** (dừng kích hoạt, ghi đường chuyển trong changelog, không xoá đột ngột).
- NEW → AUDIT → REFINE → RELEASE: `new` → `check` và audit tay → eval phiên mới, sửa theo failure → review bảo mật khi có side effect → `package`, `install` thử, owner duyệt.
- PATCH sửa typo, link; MINOR thêm workflow, reference, eval; MAJOR đổi trigger, output contract, quyền thực thi.
- AUDIT chỉ đọc; REFINE chỉ sửa khi owner yêu cầu hoặc duyệt. Mỗi thay đổi có diff, lý do, rule ID, test, cách hoàn tác. Không tự sửa mọi WARN (có thể là chủ ý của owner).

## Definition of Done

Frontmatter portable, trigger và negative scope rõ, script đã test, không secret, eval ≥3 case pass, `check` đạt, gói runtime không có fixture hay kết quả test. Production có model eval (`standards/EVALUATION_STANDARD.md`), owner, phiên bản, rollback, changelog; «model tested» cần log, ngày, phiên bản, prompt, kết quả. Ngoại lệ cần lý do trong audit.
