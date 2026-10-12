# Skill Authoring Standard — 13 quy tắc + nền tảng manifest

**Version:** 0.1.0 · **As-of:** 2026-10-12 · **Apply:** Claude Code, Codex, Google Antigravity. Đây là quy tắc **Studio** dựa trên tài liệu chính thức và bộ giải thích RoboNuggets; xem `SOURCE_TRACEABILITY.md` để phân biệt nguồn.

## Contents
- Hợp đồng portable SK-00
- Bảng 13 quy tắc
- Chỉ dẫn chi tiết SK-01 đến SK-13
- Thiết kế frontmatter và `description`
- Quy tắc với references/scripts/assets
- Definition of Done và ngoại lệ

## Hợp đồng portable SK-00

**SK-00 [MUST — Official spec]** `SKILL.md` bắt đầu ngay dòng 1 bằng YAML frontmatter bao bởi `---`. Phải có `name` và `description`. `name` dài tối đa 64 ký tự, chỉ lowercase `a-z`, số và dấu nối, không mở/đóng bằng `-`, không liên tiếp `--`, khớp tên thư mục. `description` không rỗng, không quá 1024 ký tự, nói rõ *làm gì* và *khi nào dùng*. Optional spec fields: `license`, `compatibility`, `metadata` (map string), `allowed-tools` (experimental). Vendor-specific fields không được trộn vào bản phát hành portable.

**Ví dụ chuẩn:**

```yaml
---
name: data-quality-audit
description: "Validates CSV datasets for duplicates, missing values, and schema issues. Use when checking data quality before analytics or reporting."
metadata:
  version: "1.0.0"
---
```

**Không nên:** `name: Data_Audit`, description chỉ "A useful skill", `version:` hoặc `triggers:` ở top-level của portable manifest, `hooks:` Claude Code ở file chung.

## Bảng 13 quy tắc

| ID | Quy tắc | Mức Studio | Auto-validator có thể làm? | Khi nào áp dụng |
|---|---|---|---|---|
| SK-01 | Progressive disclosure | SHOULD | Một phần: body, links | Tất cả Skill |
| SK-02 | Content lists | SHOULD | Có: Markdown reference >100 dòng | Reference dài |
| SK-03 | Degrees of freedom theo rủi ro | MUST | Không, review ngữ nghĩa | Khi thiết kế từng bước |
| SK-04 | Kiểm thử trên model sử dụng | SHOULD; MUST nếu mission-critical | Không, cần runtime | Khi release/refine |
| SK-05 | Viết ngắn & description 3rd person | SHOULD | Heuristic | Tất cả Skill |
| SK-06 | Workflow, checklist, go-back | CONDITIONAL MUST | Heuristic | Task đa bước/phức tạp |
| SK-07 | Feedback loop, errors actionable | CONDITIONAL MUST | Heuristic | Chất lượng quan trọng |
| SK-08 | Template, examples, conditional branches | SHOULD | Review | Format/style có ràng buộc |
| SK-09 | Shareability & dependencies | MUST nếu có dependency | Partly | Script/package/network/tool |
| SK-10 | Enforce must-hold bằng controls | CONDITIONAL MUST | Manual/security test | Side effect/rủi ro cao |
| SK-11 | Evals trước khi mở rộng | SHOULD; MUST nếu mission-critical | Check schema/test count | Skill được vận hành dài hạn |
| SK-12 | Quy tắc quan trọng lên đầu | SHOULD | Review | Long-running tasks |
| SK-13 | Không yêu cầu lộ suy luận nội bộ | MUST | Heuristic+manual | Mọi Skill |

*Source: RoboNuggets PDF trang 4–10 (10 rules +3 bonus), Anthropic official Best Practices, Claude Code Skills, Claude prompting guides; mapping 46 checks xem tài liệu khác. Mức MUST/SHOULD là **Studio governance**, không trích nguyên nhãn của Anthropic.*

## Chỉ dẫn chi tiết

### SK-01 — Progressive Disclosure [SHOULD]

**Why:** giữ discovery/routing ngắn, tránh context bị chiếm bởi tài liệu ít liên quan. `SKILL.md` nên <500 dòng body; phần tài liệu sâu chuyển sang reference. File reference quan trọng nên được liên kết thẳng từ `SKILL.md` dù được lưu trong subfolder nhiều cấp.

**Check:** đếm dòng sau frontmatter, phát hiện link hỏng hoặc reference chỉ reachable qua reference khác, audit những file luôn phải đọc mỗi run (có thể gộp phần cốt lõi vào entrypoint).

**Fix:** tách theo nhiệm vụ thật (`references/dax.md`, `references/security.md`); với mỗi file thêm dòng "Read when...". Không được chuyển các guardrail quan trọng vào reference bị đọc tùy ý.

### SK-02 — Content Lists [SHOULD]

**Why:** agent có thể chỉ xem một phần tài liệu dài, Contents đầu file giúp nhìn phạm vi.

**Check:** reference `.md` >100 dòng cần `## Contents` hoặc `## Mục lục` ở phần đầu.

**Fix:** thêm 3–10 mục điều hướng đúng thứ tự; không áp dụng cho file Python, CSV, hình ảnh hoặc XLSX.

### SK-03 — Degrees of Freedom [MUST trong thiết kế]

| Freedom | Khi dùng | Lệnh mẫu |
|---|---|---|
| High | Brainstorming, viết nháp sáng tạo | "Choose an appropriate outline; preserve facts" |
| Medium | Báo cáo chuẩn, mapping nguồn, DAX coding conventions | "Follow the preferred 5-section template; adapt examples" |
| Low | Payment/deletion/deployment/migration | "Run `scripts/check_plan.py` then execute approved command" |

**Why:** nếu làm khác sẽ gây thiệt hại, dùng scripts/schema/permissions thay vì prose rộng. Dùng mixed freedom trong cùng Skill; không phải mọi bước đều cứng.

**Check:** với mỗi bước hỏi "nếu agent làm khác sẽ gây tổn thất gì?". Nếu không ảnh hưởng, tăng freedom. Nếu mất tiền/xóa dữ liệu, giảm freedom và yêu cầu approval.

### SK-04 — Test on actual models [SHOULD; production-critical MUST]

**Why:** Skill là hướng dẫn bổ sung vào năng lực model. Prompt nhiều bước từng cần với model cũ có thể dư với model mới. Không xóa rule theo trực giác.

**Check:** run ít nhất 3 tình huống thực, on/off Skill, trên model và runtime mục tiêu. Ghi quality score, token/latency nếu có quan sát đáng tin, các lần đọc thiếu files, và failure.

**Fix:** giữ bản cũ và bản rút gọn; thử A/B ở fresh session, chỉ xóa instruction nếu không làm kém kết quả. Không tự khẳng định “Claude 5.5 tự hiểu” mà chưa chạy eval.

### SK-05 — Concise and discoverable [SHOULD]

**Why:** mọi description đã nạp đều tốn context. Description là cơ chế lựa chọn, không phải giới thiệu thương hiệu.

**Check:** description ngôi thứ ba ("Validates ..."), nói rõ công việc và điều kiện "Use when ..."; kiểm tra skill overlap. Xóa giải thích khái niệm phổ thông không thay đổi hành vi.

**Fix:** nêu 2–3 trigger thực và negative scope nếu cần. Một thuật ngữ cho mỗi khái niệm. Không đưa prompt marketing vào manifest.

### SK-06 — Checkable workflow [CONDITIONAL MUST]

**Why:** tác vụ dài hay bị bỏ bước hoặc hoàn thành vội. Nêu bước và điều kiện `Done when`, đường quay lại khi test fail.

```text
Plan -> Inspect inputs -> Execute -> Validate -> Report
If validation fails, return to Inspect/Execute and run validation again.
```

Checklist là công cụ tổ chức cho tác vụ thực sự phức tạp, không phải làm nghi thức với tác vụ nhỏ.

### SK-07 — Feedback loop [CONDITIONAL MUST]

**Why:** output chất lượng cao không được chấp nhận chỉ vì agent nói "done". Chạy `validate -> diagnose -> fix -> revalidate`, giới hạn attempts hợp lý và báo blocker thay vì lặp vô hạn.

**Check:** validator/script cung cấp lỗi gồm tên trường, giá trị sai, các giá trị đúng hoặc hướng khắc phục. Review phong cách cũng có thể dùng style guide nhưng phải ghi tiêu chí đánh giá.

### SK-08 — Templates / Examples / Branches [SHOULD]

**Why:** với kết quả định dạng chặt, ví dụ thật hữu ích hơn những mô tả trừu tượng. Template phải ghi **Strict** (schema/API/csv) hay **Flexible** (memo/report).

- Khi output có format strict: dùng schema/validator exact.
- Khi output phụ thuộc style: đưa 1–3 cặp input/output.
- Nếu 2 nhánh khác nhau: bắt đầu bằng nhánh "Create new?" / "Edit existing?" và đưa reference riêng.
- Chọn một default và chỉ một escape hatch cần thiết, thay vì nhiều option không có rule lựa chọn.

### SK-09 — Shareability [MUST khi có dependency]

**Why:** máy khác có thể thiếu thư viện, quyền mạng hoặc CLI. Ghi tool, version constraint nếu thực sự cần, cách cài và fallback. Đường dẫn tương đối với Skill, forward slash trong Markdown (trừ hệ thống lệnh platform-specific).

**Check:** các file scripts có hướng dẫn "Run" hay "Read"; có no-network scenario; file path không đóng cứng `C:\Users\...` hay `/Users/duc/...`; không chứa secret. Lưu assets trong chính Skill. Sử dụng environment/path abstraction khi chuyển agent; `${CLAUDE_SKILL_DIR}` là Claude-specific, không portable.

### SK-10 — Must-hold enforcement [CONDITIONAL MUST]

**Why:** lời nhắc có thể bị bỏ qua, context có thể bị compact. Nếu có rủi ro mất dữ liệu/phát sinh tiền/gửi ra ngoài, cần permission/hook/tool gate thực tế.

**Check:** xác định sự kiện `PreToolUse` nếu Claude Code có hook được hỗ trợ; với Codex/AGY phải tra adapter về cơ chế kiểm soát tương đương, không copy YAML hook giữa các agent. Test `allow` và `block` case độc lập. Hook Skill của Claude có lifecycle sau invocation; guardrail toàn cục phải thuộc policy runtime.

### SK-11 — Build evaluations first [SHOULD, production-critical MUST]

**Why:** tránh viết tài liệu hoành tráng nhưng không sửa lỗi thật. Trước khi mở rộng Skill, tạo 3 prompts thực tế và baseline no-skill; trong mỗi repo, thêm một negative trigger.

**Check:** `evals/<name>/cases.json` hợp lệ và có 3 case, rubrics/owner/version. `studio.py evals` test schema; chạy model thật cần [evals/RUNBOOK.md](../evals/RUNBOOK.md).

### SK-12 — Critical instructions near top [SHOULD]

**Why:** Claude Code có compaction/lifecycle chỉ gắn lại phần đầu của Skill ở một số hoàn cảnh; nhưng không nhầm threshold 500 dòng với 5000 tokens.

**Check:** các quy tắc phải giữ xuyên workflow nằm ngay sau frontmatter và purpose. Detail/history/example dài ở references/assets. Với must-hold enforcement vẫn cần runtime gate riêng, không chỉ chuyển đoạn văn lên đầu.

### SK-13 — No reasoning echo [MUST]

**Why:** yêu cầu agent xuất toàn bộ chain-of-thought nội bộ có thể dẫn đến refusal trên các model và không cần thiết để audit chất lượng.

**Fix:** thay "show your private chain of thought step by step" bằng "give conclusion, assumptions, verifiable evidence, tests and a concise explanation". Không cấm giải thích lập luận cấp cao hoặc mô tả hành động đã làm.

## Hướng dẫn với resources

- `references/`: chỉ dẫn tư duy, khái niệm nghiệp vụ, tiêu chuẩn, mapping; tên file nói rõ chức năng.
- `scripts/`: hành động deterministic, error handling/usage/documentation; không đọc toàn bộ script vào context khi chỉ cần chạy.
- `assets/`: biểu mẫu, dữ liệu mẫu, ảnh, schema, layout, config được dùng trực tiếp cho output. Phân loại theo vai trò, không phải đuôi file.
- `evals/`: để ở cấp repository theo chuẩn Studio; không đóng gói runtime; chứa stimuli, oracle/rubrics, baseline logs **từ run thật**.

## Definition of Done

Một Skill mới hoàn thành khi: frontmatter portable, trigger/negative scope rõ, tài liệu trực tiếp truy xuất, steps có acceptance, scripts tested, assets không rò secret, eval schema pass, 3+ case và model eval có kết quả ghi nhận nếu Skill production. Không đồng nhất "static validation PASS" với "model execution PASS".

**Ngoại lệ:** 500 dòng, 100 dòng, nội dung checklist, test scope có thể điều chỉnh theo quy mô dự án; phải có rationale trong audit và không đưa sự điều chỉnh này vào vendor standard.

**Sources:** [Anthropic Skill Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices), [Claude Code Skills](https://code.claude.com/docs/en/skills), [Agent Skills Spec](https://agentskills.io/specification), PDF *The 10 SKILL Rules* (trang 4–10), [RoboNuggets community repository](https://github.com/robonuggets/skill-creator-plus).
