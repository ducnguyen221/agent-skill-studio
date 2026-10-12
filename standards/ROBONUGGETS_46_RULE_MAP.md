# RoboNuggets 46 Checks — Bản đồ chuyển đổi vào Agent Skill Studio

**Nguồn:** [robonuggets/skill-creator-plus](https://github.com/robonuggets/skill-creator-plus) (đọc README, `SKILL.md`, references/audit-checklist.md, references/testing.md). Đây là **repo cộng đồng** MIT, không phải sản phẩm chính thức của Anthropic. Mapping dưới đây là **phân loại của Studio**, không sao chép nội dung validator của repo.

## Nguyên tắc mapping

- `Portable`: kiểm tra theo đặc tả chung; `Claude`: tính năng đặc thù Claude Code; `Studio`: kinh nghiệm quản trị nội bộ.
- Mã `FM1..LB2` xuất phát từ README của repo. Mã `SK-00..SK-13` là chuẩn thiết kế tại `SKILL_AUTHORING_STANDARD.md`.
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
| ST5 | TOC for reference >100 lines | SK-02 | Best practice | Static WARN |
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

## Chủ động không sao chép nguyên xi

- Trường frontmatter ngoài 6 fields chỉ được dùng trong **target-specific** Claude variant.
- `Hooks` là một hình thức enforcement của Claude, không được biến thành thiết kế portable duy nhất.
- Script validator của cộng đồng là nguồn tham khảo kiểm tra, **không** được xem như thẩm quyền kỹ thuật mạnh hơn tài liệu chính thức.
- Một rule thuộc nhóm "Advice" có thể bổ ích nhưng không được trình bày như điều kiện bắt buộc của Anthropic.

## Backlog review semantic (không thể kiểm tra hoàn toàn bằng regex)

1. Skill quá chung, trùng trigger với Skill khác, hoặc quá nhiều phạm vi.
2. Ref quá lớn nhưng được đọc ở mọi run, làm mất lợi thế disclosure.
3. Cơ chế enforce nguy hiểm chỉ là một dòng prose.
4. Skill tạo output đẹp nhưng sai factual/harness task.
5. Rule có thể bỏ được trên model mới: phải chạy eval, không xóa dựa vào cảm giác.

**Tổng số community rule IDs trong ma trận: 46** (FM 5 + DS 4 + ST 7 + CT 10 + WF 4 + SC 5 + NM 5 + HK 1 + TS 3 + LB 2).
