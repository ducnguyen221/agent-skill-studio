# MEMO-SKILL-V0 — chuẩn viết skill tạm
Date: 2026-10-22
Trạng thái: v0 tạm; thay bằng chuẩn v1 khi SPR-33 đóng (Cổng 2).
Người dùng: SPR-31 và SPR-32 viết skill theo hai bảng dưới; lớp (a) là hình thức, lớp (b) là văn phong cho Claude 5.x.
Kiểm: `python <worktree>/studio.py validate <skill>` — bản `main` đủ cho FM/DS/ST cũ; `--target` và `CT10` chỉ có ở worktree SPR-33 tới Cổng 2.

Nguồn đã mở lại ngày 22/10/2026: **[spec]** agentskills.io/specification · **[bp]** platform.claude.com/…/agent-skills/best-practices · **[cc]** code.claude.com/docs/en/skills · **[ab]** agentskills.io/skill-creation/best-practices · **[ae]** agentskills.io/skill-creation/evaluating-skills · **[pb]** platform.claude.com/…/claude-prompting-best-practices · **[fable-5]** …/prompting-claude-fable-5 · **[sonnet-5.5]** …/prompting-claude-sonnet-5-5. Câu trích: `evidence/sources.md` của SPR-33.

## Lớp (a) — hình thức đã ổn định

| Dòng | Nội dung | Nguồn |
|---|---|---|
| (a1) | `name` 1–64 ký tự, `a-z0-9-`, không đầu/cuối `-`, không `--`, khớp tên thư mục; không thẻ XML, không chứa "anthropic" hay "claude" | [spec], [bp] |
| (a2) | `description` 1–1 024 ký tự, không thẻ XML, ngôi thứ ba, nói làm gì + khi nào, có từ khoá người dùng hay nói | [spec], [bp] |
| (a3) | Claude Code cắt `description` + `when_to_use` ở 1 536 ký tự và dặn đặt use case chính lên đầu → Studio: cụm kích hoạt nằm trong ~500 ký tự đầu | [cc] + [nội bộ] cho con số 500 |
| (a4) | Khoá portable: `license`, `compatibility` ≤500, `metadata` (map chuỗi), `allowed-tools` (thử nghiệm). Khoá riêng Claude Code chỉ dùng cho bản đích Claude Code vì claude.ai/API báo lỗi cứng khi gặp khoá lạ | [spec], [cc] |
| (a5) | Thân <500 dòng và <5 000 token; sau compaction Claude Code giữ 5 000 token đầu mỗi skill (tổng 25 000) → điều phải giữ đặt gần đầu | [spec], [cc] |
| (a6) | Tham chiếu một cấp từ `SKILL.md`, nói *khi nào* đọc từng file; file >100 dòng có mục lục | [bp], [ab] |
| (a7) | Đường dẫn dùng `/`; nói rõ "chạy" hay "đọc" script; khai phụ thuộc; tên MCP dạng `Server:tool`; API không có mạng, không cài gói | [bp] |
| (a8) | Eval ≥3 case, có baseline không-skill hoặc bản cũ; định dạng agentskills là `evals/evals.json`; Studio giữ `cases.json` ngoài skill kèm bộ xuất | [bp], [ae] + [nội bộ] |
| (a9) | Mục lục `## Contents` ngay dưới tiêu đề cấp một, mỗi dòng `- <Tên mục ##> — <khi nào đọc>`, ≤12 dòng; không có luật "N dòng đầu" | [bp] + [nội bộ] cho định dạng |

## Lớp (b) — văn phong cho Claude 5.x

| Dòng | Nội dung | Nguồn |
|---|---|---|
| (b1) | Chỉ thêm điều Claude chưa biết; với mỗi đoạn tự hỏi "bỏ câu này thì agent có làm sai không?" | [bp], [ab] |
| (b2) | Nêu lý do thay vì mệnh lệnh; chữ ép buộc kiểu `CRITICAL: You MUST…` làm model gần đây kích hoạt quá đà → viết "Use … when …"; strict template vẫn được dùng "ALWAYS" | [pb], [ab], [bp] |
| (b3) | Mức tự do theo độ mong manh của việc; một mặc định kèm một lối thoát, không thực đơn | [bp], [ab] |
| (b4) | Mục `## Gotchas` trong `SKILL.md`: sự thật trái giả định hợp lý; sửa agent một lần thì thêm một dòng | [ab] |
| (b5) | Skill viết cho model cũ thường quá cứng — rà và cân nhắc bỏ, nhưng Studio chỉ bỏ khi eval cho thấy không kém | [fable-5] + [nội bộ] `SK-04` |
| (b6) | Không bảo model chép/giải thích suy luận nội bộ ra response (bị từ chối loại `reasoning_extraction`); được xin giải thích ngắn hoặc tóm tắt hành động | [fable-5], [sonnet-5.5] |
| (b7) | Nêu ranh giới làm/không làm; chỉ dừng hỏi ở thao tác không đảo ngược, đổi phạm vi, hoặc input chỉ người dùng có | [fable-5] |
| (b8) | Thử trên đúng model sẽ dùng; chưa chạy thì ghi `not_run`, không suy ra "tự hiểu" | [bp] + [nội bộ] |
| (b9) | Thân tiếng Việt (tạm tới chuẩn Việt v1): chữ dựng sẵn NFC, kết luận trước, câu ≤25 từ, frontmatter tiếng Anh | [nội bộ] |

## Năm nguyên tắc tạm nếu memo đến trễ
(b1) chỉ thêm điều Claude chưa biết · (b2) nêu lý do, không viết hoa ép buộc · (a3) cụm kích hoạt trong ~500 ký tự đầu của `description`
(b4) có `## Gotchas` · (b6) không bảo model phơi suy luận nội bộ. Hết hạn khi chuẩn v1 của SPR-33 có hiệu lực.
