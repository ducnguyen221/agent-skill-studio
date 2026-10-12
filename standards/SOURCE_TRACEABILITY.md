# Source Traceability — Nguồn gốc và giới hạn của 13 quy tắc

**Checked:** 2026-10-12. Tài liệu này phân biệt **nguồn chính thức / tài liệu cộng đồng / quyết định nội bộ**. Không viện dẫn PDF như thể PDF là văn bản chính thức của Anthropic.

## Contents
- Nguồn đã đối chiếu
- Ma trận 13 quy tắc
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

**Community / derivative**

- [C1 — YouTube VQyYzLJ6xos](https://www.youtube.com/watch?v=VQyYzLJ6xos), RoboNuggets/Jay E, nội dung 10 rule. Lưu ý: chúng tôi dựa vào transcript công khai và PDF kèm theo, **không tự tuyên bố đã phát trực tiếp video**.
- **C2 — PDF đính kèm từ người dùng** *The 10 SKILL Rules* (13 trang). Trang 3: audit prompt; trang 4–9: 10 rule; trang 10: 3 bonus; trang 11: Skill Creator Plus; trang 13: recap/source links. PDF là một bản diễn giải có dẫn link gốc, không phải official specs.
- [C3 — robonuggets/skill-creator-plus](https://github.com/robonuggets/skill-creator-plus): community skill kiểm tra 46 rule IDs và NEW/AUDIT/REFINE; MIT license; không affiliation Anthropic.

## Ma trận 13 quy tắc

| Studio | PDF page | Official reference | Phần chính thức đã xác minh | Phần là quyết định Studio |
|---|---|---|---|---|
| SK-01 Progressive disclosure | 4 | A1, A2 | `SKILL.md` làm overview, khuyến nghị <500 body lines, tránh deeply nested reference | `WARN` nếu >=500 dòng; giữ links tới tất cả reference quan trọng |
| SK-02 Content lists | 5 | A2 | Reference >100 lines nên có TOC | `WARN`, không biến thành lỗi cú pháp |
| SK-03 Freedom | 5 | A2 | High/medium/low specificity theo fragility | Studio định nghĩa MUST phải phân loại cho workflow có rủi ro |
| SK-04 Model testing | 6 | A2, prompting guides | Test với model sử dụng, older scaffolding có thể quá chặt | Production-critical bắt buộc log theo model |
| SK-05 Concise description | 6 | A1, A2, A3 | Name/description spec, what+when; third person best practice | Thực thi heuristic trigger |
| SK-06 Workflows/checklists | 7 | A2 | Steps/checklists/go-back cho việc phức tạp | Conditional MUST, không bắt task nhỏ checklists dài |
| SK-07 Feedback loops | 7 | A2 | Validate -> fix -> repeat, action-guiding errors | Set release gate theo mức rủi ro |
| SK-08 Common patterns | 8 | A2 | Templates, examples, conditional workflow | Nêu explicit STRICT vs FLEXIBLE |
| SK-09 Shareability | 8 | A1, A2 | Dependencies, paths, environment assumptions | Chặn máy-specific paths trong package ở mức phù hợp |
| SK-10 Hooks | 9 | A3, A4 | Claude Code support lifecycle hooks, must-hold controls | Portable controls khác nhau theo runtime, không ép `hooks:` common |
| SK-11 Evals first | 10 | A2, A3 | >=3 evals recommended, baseline no-skill, fresh sessions | `evals/` **ngoài skill** là Studio-only policy |
| SK-12 Critical instructions first | 10 | A3 | After compaction, may reattach only beginning / first 5000 tokens each Skill | Keep safety + DoD near top of every Skill |
| SK-13 No reasoning echo | 10 | Claude prompting guides | Some Claude models may refuse requests to expose internal reasoning | MUST tránh yêu cầu chain-of-thought trên tất cả agent |

## Khác biệt cần lưu ý

1. **Tên video nói "10 NEW"**: không chứng minh cả mười là feature mới cùng ngày. Các hướng dẫn gốc được thu thập thành top 10; bản PDF thừa nhận những quy tắc từ nguồn chính thức.
2. **Mốc 500 lines / >100 lines**: Anthropic gọi là khuyến nghị chất lượng; `Agent Skills Specification` không áp đặt file không thể load khi vượt mốc.
3. **5000 tokens ở Claude Code compaction**: không phải giới hạn file size của chuẩn portable; ưu tiên nội dung quan trọng đầu SKILL.md.
4. **Claude versions Fable 5, Opus/Sonnet 5.5:** thông tin này được PDF và hướng dẫn model riêng đề cập; về lâu dài dùng action principle "test on models actually deployed", không đóng cứng version vào rule.
5. **Claude skill hook**: khi invoke, hook có scope lifecycle của Skill, không bảo vệ trước invoke hoặc runtime khác.
6. **PDF trang 11 so sánh Anthropic skill-creator (300 lines vs 100)** là claim của tác giả community, **chưa sử dụng làm fact chắc chắn về code upstream**. Xem chính sách version before copying.
7. **Antigravity migration date:** các URL chính thức `antigravity.google` và `www.antigravity.google` từng có thông tin thời hạn workflow khác nhau (October 19 vs November 1 2026 trong kết quả công khai). Không đóng cứng một ngày migration thành quy tắc; cần xác minh bản docs/cấu hình runtime tại thời điểm triển khai.
8. **Không có automatic evaluation model** trong bộ CLI này. Static validator và model A/B test là hai tầng khác nhau.

## Quy trình cập nhật

- Mỗi claim có source link, date checked và vị trí PDF phù hợp.
- Khi vendor docs cập nhật, ghi phiên bản mới, rà lại các rule `MUST/SHOULD`, adapter và test case. Đánh dấu stale nếu không thể kiểm tra.
- Không ghi dữ liệu user/customer vào upstream evidence log; chỉ lưu synthetic fixtures và link nguồn công khai.

### Citation practice

Nguồn chính thức dùng để kiểm tra chức năng/format của vendor; README cộng đồng dùng để xác định nội dung repo RoboNuggets; PDF dùng để xác định chính xác 13 quy tắc mà user muốn hệ thống hóa. Không lấy số sao GitHub/stars làm evidence về độ tin cậy.
