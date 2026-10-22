# Claude Code Adapter — Cấu hình riêng cho Claude

Checked: 2026-10-23 · nguồn đã mở lại: [Official Skills](https://code.claude.com/docs/en/skills) (đích cài, danh sách khoá frontmatter, giới hạn danh sách skill). [Official Memory](https://code.claude.com/docs/en/memory) và [Official Hooks](https://code.claude.com/docs/en/hooks): `not_run:chưa mở lại` ở lần này, phần liên quan giữ nguyên văn bản cũ, kiểm lại trước khi dựa vào.

## Phạm vi

Chỉ áp dụng khi chạy **Claude Code**. Portable `SKILL.md` không được tùy tiện mang `hooks`, `disable-model-invocation`, `context`, `agent`, `paths`, `background`, model/effort hay dynamic injection sang Codex/Antigravity.

## Discovery và instruction

- Project Skills: `.claude/skills/<skill-name>/SKILL.md`.
- User Skills: `~/.claude/skills/<skill-name>/SKILL.md`. Lệnh `install --user` của Studio **không hỗ trợ** đích này (`--agent claude --user` thoát 2, `ERROR: --user is not supported for claude; use --workspace`); muốn cài cấp người dùng thì tự chép thư mục vào đó.
- Project instructions: `CLAUDE.md`, có thể tham chiếu chung `@AGENTS.md`. Đây là cú pháp import **được docs Claude xác nhận**; nhập một file đồng nghĩa file đó được nạp vào context, không tiết kiệm token nếu luôn import.
- Rules thường trực theo file: `.claude/rules/*.md` (scoped khi tính năng hỗ trợ).
- Hook trong Skill frontmatter có lifecycle từ khi invoked; guardrail tổ chức bắt buộc phải cấu hình cấp cao hơn ở runtime/policy.

## Cài Skill Studio

```bash
mkdir -p ./target-project   # --workspace phải là thư mục có sẵn, thiếu thì thoát 2
python3 studio.py install skills/skill-creator-studio --agent claude --workspace ./target-project
# sau đó trong Claude Code kiểm tra khả năng tìm /skill-creator-studio
```

Không auto-install khi chỉ clone repo: `skills/` là canonical source; project discovery thuộc `.claude/skills/`.

## Frontmatter: portable vs Claude extension

```yaml
# Portable, có thể đưa Claude Code / claude.ai / Codex / AGY
---
name: audit-my-data
description: "Audits tabular data. Use when checking dataset completeness, keys and null rates."
metadata:
  version: "1.0.0"
---
```

```yaml
# CLAUDE CODE ONLY, khi người dùng chủ động chọn feature này
---
name: deploy-preview
description: "Deploys a preview build. Use when explicitly asked to deploy a preview environment."
disable-model-invocation: true
# hooks: phải kiểm tra event/matcher/hook schema thực tế theo version
---
```

Không cho rằng `hooks` chỉ là đề xuất văn bản: nó là code trigger. Khi cần, review script và test hành vi allow/block trước khi publish.

## Lưu ý khi viết cho Claude Code (chuẩn SK-00…SK-15)

- Sau compaction, Claude có thể chỉ tái gắn phần đầu của Skill (docs nêu first 5,000 tokens mỗi Skill trong lifecycle liên quan). Đưa safety/doD lên đầu; không nhầm với gợi ý 500 dòng.
- Dùng `description` để phát hiện; body được đọc khi Skill invoked.
- `context: fork`/subagent và `${CLAUDE_SKILL_DIR}` là Claude-specific; không gửi raw sang runtime khác.
- Nếu Skill phải chuyển qua claude.ai/Skills API, chỉ dùng sáu portable keys: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`.

## 14 khoá frontmatter chỉ có ở Claude Code

Docs Claude Code liệt kê các khoá sau ngoài sáu khoá portable (`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`); Studio giữ cùng 14 khoá trong `CLAUDE_CODE_KEYS`:

`when_to_use`, `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `disallowed-tools`, `model`, `effort`, `context`, `agent`, `background`, `hooks`, `paths`, `shell`.

Mặc định (`--target portable`) `validate` báo lỗi `FM4` cho từng khoá này. Với `python3 studio.py validate <skill> --target claude-code` chúng chỉ là cảnh báo `FM6` ("Claude Code only; claude.ai và API từ chối khoá này bằng lỗi cứng"). Dùng đích `claude-code` khi skill chỉ chạy trong Claude Code; skill portable thì giữ mặc định.

## Giới hạn danh sách skill

Docs: phần `description` cộng `when_to_use` của mỗi skill bị cắt ở 1 536 ký tự trong danh sách skill; đặt ý "dùng khi nào" lên đầu. Chuẩn Studio chặt hơn (`description` ≤1 024 ký tự, SK-00) nên bám chuẩn Studio. `SKILL.md` dưới 500 dòng.

## Kiểm tĩnh

`claude plugin validate <thư mục> --json` chỉ để ghi nhận (không làm cổng của Studio). Lần chạy 2026-10-23 trên `.claude/skills` vừa cài: exit 0, `success: true`, `contents: []`.

## Smoke-test

1. `/context` xác nhận `CLAUDE.md` được nạp và `@AGENTS.md` không bị bỏ qua.
2. Yêu cầu trong phạm vi kích hoạt đúng Skill; yêu cầu ngoài phạm vi không kích hoạt.
3. Chạy 3 test prompts trong `evals/<name>/cases.json` ở new sessions có và không có Skill.
4. Với Skill chỉ người dùng được gọi, xác minh không auto-invoke.
5. Test hook deny + allow chỉ trên sandbox mock; không dùng payment/deploy thật.

**Nguyên tắc:** không copy cấu hình Claude thành portable SKILL.md. Hãy giữ base Skill chung và tạo adapter/variant nếu tính năng riêng là cần thiết.
