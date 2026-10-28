---
title: "Source Traceability — Nguồn gốc và giới hạn của quy tắc SK-00…SK-15"
status: active
updated: 2026-10-28
---
# Source Traceability — Nguồn gốc và giới hạn của quy tắc SK-00…SK-15

**Checked:** 2026-10-22 (A10–A16 mở lại ngày này; A1–A9 giữ mốc 2026-10-12). Tài liệu này phân biệt **nguồn chính thức / tài liệu cộng đồng / quyết định nội bộ**. Không viện dẫn PDF như thể PDF là văn bản chính thức của Anthropic. `Official` trong bảng nghĩa là sự kiện hay đặc tả do nhà cung cấp công bố, không đồng nghĩa họ gắn rule đó là MUST.

## Contents
- Nguồn đã đối chiếu
- Ma trận quy tắc
- Bản đồ 46 check RoboNuggets
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

## Bản đồ 46 check RoboNuggets

**Nguồn:** [robonuggets/skill-creator-plus](https://github.com/robonuggets/skill-creator-plus) (đọc README, `SKILL.md`, references/audit-checklist.md, references/testing.md). Đây là **repo cộng đồng** MIT, không phải sản phẩm chính thức của Anthropic. Mapping dưới đây là **phân loại của Studio**, không sao chép nội dung validator của repo.

### Nguyên tắc mapping

- `Portable`: kiểm tra theo đặc tả chung; `Claude`: tính năng đặc thù Claude Code; `Studio`: kinh nghiệm quản trị nội bộ.
- Mã `FM1..LB2` xuất phát từ README của repo. Mã `SK-00..SK-15` là chuẩn thiết kế tại `SKILL_AUTHORING_STANDARD.md`.
- Máy có thể tự kiểm tra syntax/paths, nhưng các vấn đề chất lượng (đúng trigger, quá chi tiết, risk) vẫn cần reviewer/agent eval.

| Community ID | Ý chính | Studio mapping | Phạm vi | Check |
|---|---|---|---|---|
| FM1 | YAML parses, starts line 1 | SK-00 | Portable | Static |
| FM2 | Valid name and folder match | SK-00 | Portable | Static |
| FM3 | Activity-oriented name | SK-05 | Studio | Review |
| FM4 | Recognized fields per runtime | SK-00 | Portable/Claude | Static |
| FM5 | Invocation deliberately configured | SK-03, SK-10 | Claude | Review |
| DS1 | Description length/format | SK-00 | Portable | Static |
| DS2 | Description third-person | SK-05 | Best practice | Heuristic |
| DS3 | What+when and user language | SK-05 | Portable/Best practice | Review |
| DS4 | Important use-case first, listing budget | SK-05 | Claude | Static+Review |
| ST1 | SKILL body <500 lines | SK-01 | Best practice | Static WARN |
| ST2 | Important rules near top | SK-12 | Claude | Review |
| ST3 | Break out details, on demand | SK-01 | Portable | Review |
| ST4 | References directly linked from SKILL | SK-01 | Best practice | Static+Review |
| ST5 | TOC for reference >100 lines | SK-15 | Best practice | Static WARN |
| ST6 | Reachable, named files, no backups | SK-01, SK-09 | Studio | Static+Review |
| ST7 | POSIX path slashes in docs | SK-09 | Best practice | Static heuristic |
| CT1 | Remove generic redundant context | SK-05 | Best practice | Review |
| CT2 | Freedom per risk/fragility | SK-03 | Best practice | Review |
| CT3 | Avoid stale time-sensitive guidance | SK-05 | Best practice | Review |
| CT4 | Consistent terminology | SK-05 | Best practice | Review |
| CT5 | Label strict/flexible templates | SK-08 | Best practice | Review |
| CT6 | Examples for style-sensitive output | SK-08 | Best practice | Review |
| CT7 | One default plus escape hatch | SK-08 | Studio | Review |
| CT8 | Full MCP tool names | SK-09 | Best practice | Review |
| CT9 | No TODO/FIXME placeholders in release | SK-07 | Studio | Static WARN |
| CT10 | One rule in one location | SK-05 | Studio | Review |
| WF1 | Checklist, checkable done, go-back | SK-06 | Best practice | Review |
| WF2 | Validator feedback loop | SK-07 | Best practice | Review |
| WF3 | Plan/validate/execute before destructive | SK-03, SK-10 | Best practice | Review |
| WF4 | Standing instructions vs one-time lines | SK-12 | Claude | Review |
| SC1 | Solve errors in script instead of defer | SK-07 | Best practice | Code review |
| SC2 | Explain constants | SK-09 | Best practice | Code review |
| SC3 | Distinguish run vs read script | SK-09 | Best practice | Review |
| SC4 | Actionable error output | SK-07 | Best practice | Code review |
| SC5 | Explicit package requirements/install | SK-09 | Best practice | Static+Review |
| NM1 | Remove over-prescription after testing | SK-04, SK-05 | Model-specific | Eval |
| NM2 | Avoid internal reasoning echo | SK-13 | Model-specific | Static heuristic |
| NM3 | Explain why rule exists | SK-05 | Best practice | Review |
| NM4 | Brief steering, capitals sparingly | SK-05 | Best practice | Review |
| NM5 | Explicit verification, fresh checker | SK-07, SK-11 | Best practice | Review |
| HK1 | Must-hold -> hook/policy | SK-10 | Claude-specific hook | Security test |
| TS1 | >=3 evals, baseline before skill | SK-11 | Best practice | Static+Eval |
| TS2 | Fresh session, Skill on/off | SK-11 | Best practice | Eval |
| TS3 | Models actually used | SK-04 | Best practice | Eval |
| LB1 | No competing triggers | SK-05 | Studio | Library review |
| LB2 | Unused skills managed/disabled | SK-05 | Claude-specific tooling | Library review |

### Chủ động không sao chép nguyên xi

- Trường frontmatter ngoài 6 fields chỉ được dùng trong **target-specific** Claude variant.
- `Hooks` là một hình thức enforcement của Claude, không được biến thành thiết kế portable duy nhất.
- Script validator của cộng đồng là nguồn tham khảo kiểm tra, **không** được xem như thẩm quyền kỹ thuật mạnh hơn tài liệu chính thức.
- Một rule thuộc nhóm "Advice" có thể bổ ích nhưng không được trình bày như điều kiện bắt buộc của Anthropic.

### Backlog review semantic (không thể kiểm tra hoàn toàn bằng regex)

1. Skill quá chung, trùng trigger với Skill khác, hoặc quá nhiều phạm vi.
2. Ref quá lớn nhưng được đọc ở mọi run, làm mất lợi thế disclosure.
3. Cơ chế enforce nguy hiểm chỉ là một dòng prose.
4. Skill tạo output đẹp nhưng sai factual/harness task.
5. Rule có thể bỏ được trên model mới: phải chạy eval, không xóa dựa vào cảm giác.

**Tổng số community rule IDs trong ma trận: 46** (FM 5 + DS 4 + ST 7 + CT 10 + WF 4 + SC 5 + NM 5 + HK 1 + TS 3 + LB 2).

## Khác biệt cần lưu ý

1. **Tên video nói "10 NEW"**: không chứng minh cả mười là feature mới cùng ngày. Các hướng dẫn gốc được thu thập thành top 10; bản PDF thừa nhận những quy tắc từ nguồn chính thức.
2. **Mốc 500 lines / >100 lines**: Anthropic gọi là khuyến nghị chất lượng; `Agent Skills Specification` không áp đặt file không thể load khi vượt mốc.
3. **5000 tokens ở Claude Code compaction**: không phải giới hạn file size của chuẩn portable; ưu tiên nội dung quan trọng đầu SKILL.md.
4. **Claude versions Fable 5, Opus/Sonnet 5.5:** thông tin này được PDF và hướng dẫn model riêng đề cập; về lâu dài dùng action principle "test on models actually deployed", không đóng cứng version vào rule.
5. **Claude skill hook**: khi invoke, hook có scope lifecycle của Skill, không bảo vệ trước invoke hoặc runtime khác.
6. **PDF trang 11 so sánh Anthropic skill-creator (300 lines vs 100)** là lời community, lẫn hai số khác nhau. (a) Thân `SKILL.md` của skill-creator chính thức đo được 485 dòng (đo cục bộ 2026-10-22), dưới mốc 500 của A2. (b) Skill-creator khuyến nghị mục lục cho reference >300 dòng (`skill-creator/SKILL.md:98`; dossier SPR-33 `dossier-skill-docs2.md:37`), còn A2 nêu >100 dòng. Studio chọn 100 dòng cho Contents theo A2 và 500 dòng cho thân.
7. **Antigravity migration date:** các URL chính thức `antigravity.google` và `www.antigravity.google` từng có thông tin thời hạn workflow khác nhau (October 19 vs November 1 2026 trong kết quả công khai). Không đóng cứng một ngày migration thành quy tắc; cần xác minh bản docs/cấu hình runtime tại thời điểm triển khai.
8. **Không có automatic evaluation model** trong bộ CLI này. Static validator và model A/B test là hai tầng khác nhau.
9. **Số ngăn nghìn bằng khoảng trắng (`V11` của `VIETNAMESE_SKILL_WRITING.md`):** quyết định nội bộ theo khuyến nghị của Fable ngày 2026-10-22, không phải quy tắc của nguồn chính thức.

## Quy trình cập nhật

- Mỗi claim có source link, date checked và vị trí PDF phù hợp.
- Khi vendor docs cập nhật, ghi phiên bản mới, rà lại các rule `MUST/SHOULD`, `HARNESSES.md` và test case. Đánh dấu stale nếu không thể kiểm tra.
- Không ghi dữ liệu user/customer vào upstream evidence log; chỉ lưu synthetic fixtures và link nguồn công khai.

### Citation practice

Nguồn chính thức dùng để kiểm tra chức năng/format của vendor; README cộng đồng dùng để xác định nội dung repo RoboNuggets; PDF dùng để xác định các quy tắc mà user muốn hệ thống hóa. Không lấy số sao GitHub/stars làm evidence về độ tin cậy.
