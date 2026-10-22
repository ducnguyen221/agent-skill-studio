# Source Traceability — Nguồn gốc và giới hạn của quy tắc SK-00…SK-15

**Checked:** 2026-10-22 (A10–A16 mở lại ngày này; A1–A9 giữ mốc 2026-10-12). Tài liệu này phân biệt **nguồn chính thức / tài liệu cộng đồng / quyết định nội bộ**. Không viện dẫn PDF như thể PDF là văn bản chính thức của Anthropic.

## Contents
- Nguồn đã đối chiếu
- Ma trận quy tắc
- Khác biệt cần lưu ý
- Quy trình cập nhật

## Nguồn đã đối chiếu

**Primary / canonical**

- [A1 — Agent Skills Specification](https://agentskills.io/specification): `SKILL.md`, name/description, optional resources, progressive disclosure.
- [A2 — Anthropic Skill Authoring Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices): 500 lines, Contents >100, degrees of freedom, triggers, workflow, eval.
- [A3 — Claude Code Skills](https://code.claude.com/docs/en/skills): skill paths, invocation, frontmatter extensions, lifecycle, compaction, hooks, evaluations.
- [A4 — Claude Code Hooks](https://code.claude.com/docs/en/hooks): hook semantics, matchers và event lifecycle.
- [A5 — Claude Code Memory](https://code.claude.com/docs/en/memory): `CLAUDE.md` và `@AGENTS.md` import.
- [A6 — OpenAI Build Skills](https://learn.chatgpt.com/docs/build-skills): discovery `.agents/skills`, manifest/packaging, `agents/openai.yaml` optional.
- [A7 — OpenAI AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md): instruction discovery/override.
- [A8 — Google Antigravity Skills](https://www.antigravity.google/docs/skills): `.agents/skills`, `~/.gemini/config/skills`.
- [A9 — Google Antigravity Rules](https://www.antigravity.google/docs/rules/): `AGENTS.md`, `GEMINI.md`, `.agents/rules`.
- [A10 — Agent Skills: best practices](https://agentskills.io/skill-creation/best-practices): câu hỏi "agent có làm sai nếu thiếu dòng này", Gotchas, mặc định thay thực đơn.
- [A11 — Agent Skills: evaluating skills](https://agentskills.io/skill-creation/evaluating-skills): `evals/evals.json`, chạy có/không skill (định dạng cho bộ xuất eval).
- [A12 — Claude Code plugin evals](https://code.claude.com/docs/en/plugin-evals): `claude plugin eval`, case + grader, early access; định dạng khác agentskills.
- [A13 — Claude prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices): ngôn ngữ ép buộc làm model gần đây phản ứng quá đà.
- [A14 — Prompting Claude Fable 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5): skill viết cho model cũ thường quá cứng; không bắt chép suy luận; ranh giới làm/không làm.
- [A15 — Prompting Claude Sonnet 5.5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5): loại từ chối `reasoning_extraction`; vẫn được xin giải thích ngắn.

**Community / derivative**

- [C1 — YouTube VQyYzLJ6xos](https://www.youtube.com/watch?v=VQyYzLJ6xos), RoboNuggets/Jay E, nội dung 10 rule. Lưu ý: chúng tôi dựa vào transcript công khai và PDF kèm theo, **không tự tuyên bố đã phát trực tiếp video**.
- **C2 — PDF đính kèm từ người dùng** *The 10 SKILL Rules* (13 trang). Trang 3: audit prompt; trang 4–9: 10 rule; trang 10: 3 bonus; trang 11: Skill Creator Plus; trang 13: recap/source links. PDF là một bản diễn giải có dẫn link gốc, không phải official specs.
- [C3 — robonuggets/skill-creator-plus](https://github.com/robonuggets/skill-creator-plus): community skill kiểm tra 46 rule IDs và NEW/AUDIT/REFINE; MIT license; không affiliation Anthropic.

**Nội bộ / mã nguồn đo được**

- **A16 — `SYS/bootstrap/measure-skill-budget.py:13-14`** `[codex 0.147, mã]`: Codex 0.147 giới hạn `description` 1 024 ký tự và thân skill 8 000 B (`ST3`, mã thêm ở SPR-33 TK9, chưa có trong validator lúc viết chuẩn). Trần nội bộ 350 ký tự / description trong cùng file là quyết định OpcOS, không phải chuẩn Studio.

## Ma trận quy tắc

| Studio | PDF page | Official reference | Phần chính thức đã xác minh | Phần là quyết định Studio |
|---|---|---|---|---|
| SK-01 Progressive disclosure | 4 | A1, A2 | `SKILL.md` làm overview, khuyến nghị <500 body lines, tránh deeply nested reference | `WARN` nếu >=500 dòng; giữ links tới tất cả reference quan trọng |
| SK-02 Content lists và cắt gọn | 5 | A2, A10 | Reference >100 lines nên có TOC; "agent có làm sai nếu thiếu" là phép thử giữ/bỏ | Ba câu hỏi cắt (review); Contents chuyển sang `SK-15` |
| SK-03 Freedom | 5 | A2 | High/medium/low specificity theo fragility | Studio định nghĩa MUST phải phân loại cho workflow có rủi ro |
| SK-04 Model testing | 6 | A2, prompting guides | Test với model sử dụng, older scaffolding có thể quá chặt | Production-critical bắt buộc log theo model |
| SK-05 Concise description | 6 | A1, A2, A3 | Name/description spec, what+when; third person; danh sách skill cắt ở 1 536 ký tự | Thực thi heuristic trigger; con số ~500 ký tự đầu là ngưỡng nội bộ |
| SK-06 Workflows/checklists | 7 | A2 | Steps/checklists/go-back cho việc phức tạp | Conditional MUST, không bắt task nhỏ checklists dài |
| SK-07 Feedback loops | 7 | A2 | Validate -> fix -> repeat, action-guiding errors | Set release gate theo mức rủi ro |
| SK-08 Common patterns | 8 | A2 | Templates, examples, conditional workflow | Nêu explicit STRICT vs FLEXIBLE |
| SK-09 Shareability | 8 | A1, A2 | Dependencies, paths, environment assumptions | Chặn máy-specific paths trong package ở mức phù hợp |
| SK-10 Hooks | 9 | A3, A4 | Claude Code support lifecycle hooks, must-hold controls | Portable controls khác nhau theo runtime, không ép `hooks:` common |
| SK-11 Evals first | 10 | A2, A3, A11, A12 | >=3 evals recommended, baseline no-skill, fresh sessions; hai định dạng eval chính thức khác nhau | `evals/` **ngoài skill** và bộ xuất `--export` là Studio-only policy |
| SK-12 Critical instructions first | 10 | A3 | After compaction, giữ 5 000 token đầu mỗi skill, tổng 25 000 | Keep safety + DoD near top of every Skill |
| SK-13 No reasoning echo | 10 | A14, A15 | Một số model từ chối yêu cầu phơi suy luận nội bộ (`reasoning_extraction`); vẫn xin được giải thích ngắn | MUST tránh yêu cầu chain-of-thought trên tất cả agent |
| SK-14 Chữ ép buộc có lý do | — (mới) | A10, A13 | Ngôn ngữ ép buộc làm model gần đây phản ứng quá đà; giải thích lý do hiệu quả hơn mệnh lệnh cứng | `CT10` WARN; chữ trơ chỉ trong khối low-freedom hoặc khối strict |
| SK-15 Contents và điều giữ ở đầu | — (mới) | A2, A3 | Reference >100 dòng nên có mục lục; sau compaction giữ 5 000 token đầu | Thân >100 dòng nên có Contents (`ST7`), định dạng và ≤12 mục là `[nội bộ]`; không có luật chính thức "đọc N dòng đầu" |

## Khác biệt cần lưu ý

1. **Tên video nói "10 NEW"**: không chứng minh cả mười là feature mới cùng ngày. Các hướng dẫn gốc được thu thập thành top 10; bản PDF thừa nhận những quy tắc từ nguồn chính thức.
2. **Mốc 500 lines / >100 lines**: Anthropic gọi là khuyến nghị chất lượng; `Agent Skills Specification` không áp đặt file không thể load khi vượt mốc.
3. **5000 tokens ở Claude Code compaction**: không phải giới hạn file size của chuẩn portable; ưu tiên nội dung quan trọng đầu SKILL.md.
4. **Claude versions Fable 5, Opus/Sonnet 5.5:** thông tin này được PDF và hướng dẫn model riêng đề cập; về lâu dài dùng action principle "test on models actually deployed", không đóng cứng version vào rule.
5. **Claude skill hook**: khi invoke, hook có scope lifecycle của Skill, không bảo vệ trước invoke hoặc runtime khác.
6. **PDF trang 11 so sánh Anthropic skill-creator (300 lines vs 100)** là lời community, lẫn hai số khác nhau. (a) Thân `SKILL.md` của skill-creator chính thức đo được 485 dòng (đo cục bộ 2026-10-22), dưới mốc 500 của A2. (b) Skill-creator khuyến nghị mục lục cho reference >300 dòng (`skill-creator/SKILL.md:98`; dossier SPR-33 `dossier-skill-docs2.md:37`), còn A2 nêu >100 dòng. Studio chọn 100 dòng cho Contents theo A2 và 500 dòng cho thân.
7. **Antigravity migration date:** các URL chính thức `antigravity.google` và `www.antigravity.google` từng có thông tin thời hạn workflow khác nhau (October 19 vs November 1 2026 trong kết quả công khai). Không đóng cứng một ngày migration thành quy tắc; cần xác minh bản docs/cấu hình runtime tại thời điểm triển khai.
8. **Không có automatic evaluation model** trong bộ CLI này. Static validator và model A/B test là hai tầng khác nhau.

## Quy trình cập nhật

- Mỗi claim có source link, date checked và vị trí PDF phù hợp.
- Khi vendor docs cập nhật, ghi phiên bản mới, rà lại các rule `MUST/SHOULD`, adapter và test case. Đánh dấu stale nếu không thể kiểm tra.
- Không ghi dữ liệu user/customer vào upstream evidence log; chỉ lưu synthetic fixtures và link nguồn công khai.

### Citation practice

Nguồn chính thức dùng để kiểm tra chức năng/format của vendor; README cộng đồng dùng để xác định nội dung repo RoboNuggets; PDF dùng để xác định chính xác 13 quy tắc mà user muốn hệ thống hóa. Không lấy số sao GitHub/stars làm evidence về độ tin cậy.
