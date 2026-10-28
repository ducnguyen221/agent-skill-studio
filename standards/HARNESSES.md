---
title: "Harnesses — Claude Code, Codex, Antigravity"
status: active
updated: 2026-10-28
---
# Harnesses — Claude Code, Codex, Antigravity

Khác biệt giữa ba agent mà Studio cài skill vào. Không viết «mọi agent hỗ trợ» cho tính năng của một vendor. Mỗi phần mang một dòng `Checked:` (mốc kiểm và nguồn đã mở lại); điều chưa mở lại ghi `not_run:chưa mở lại` và phải kiểm lại trước khi dựa vào. Một adapter ghi rõ tên và phiên bản runtime hoặc nguồn.

## Contents
- Ma trận năng lực
- Nạp file luật
- Claude Code
- Codex
- Antigravity
- Cài và kiểm thử nhanh

## Ma trận năng lực

Checked: 2026-10-23 · nguồn mở lại: [Claude](https://code.claude.com/docs/en/skills), [Codex](https://learn.chatgpt.com/docs/build-skills), [Antigravity](https://antigravity.google/docs/skills). "Supported" nghĩa là đã tìm thấy tài liệu công khai tương ứng, không nghĩa là đã tự chạy thử runtime trong môi trường này.

| Khả năng | Claude Code | OpenAI Codex | Google Antigravity |
|---|---|---|---|
| `SKILL.md` theo Agent Skills | Supported | Supported | Supported |
| Project skill path | `.claude/skills/` | `.agents/skills/` | `.agents/skills/` |
| Global skill path | `~/.claude/skills/` | `~/.agents/skills/` | `~/.gemini/config/skills/` |
| Repo instruction | `CLAUDE.md` (`@AGENTS.md` import) | `AGENTS.md`, `.override` | `AGENTS.md` (`GEMINI.md` trỏ về `AGENTS.md`) và rules |
| Vendor-specific skill hooks in frontmatter | Claude-supported | **Không tương đương** | **Không tương đương** |
| Custom skill UI metadata | Claude extensions | `agents/openai.yaml` optional | Theo UI/runtime của AGY |
| Implicit activation by description | Supported | Supported | Supported |
| Manual invocation | `/skill-name` | `$skill-name`, `/skills` | Theo IDE/CLI, thường `/skill-name` |
| Storage của evals | Studio đặt ngoài | Studio đặt ngoài | Studio đặt ngoài |
| Portable six-key YAML frontmatter | Supported | Compatible | Compatible core, verify target version |
| Fresh-session model eval | Cần agent runtime | Cần agent runtime | Cần agent runtime |
| `studio.py install --workspace` | `.claude/skills/<tên>` | `.agents/skills/<tên>` | `.agents/skills/<tên>` |
| `studio.py install --user` | **Không hỗ trợ** (thoát 2) | `~/.agents/skills/<tên>`; `~/.agents` phải có sẵn | `~/.gemini/config/skills/<tên>` (App/IDE); `~/.gemini/config` phải có sẵn; CLI dùng đích khác |
| Khoá frontmatter ngoài sáu khoá portable | 14 khoá, chỉ qua `validate --target claude-code` (`FM6` WARN) | Không; metadata riêng ở `agents/openai.yaml` (tuỳ chọn) | Không có trong docs đã đọc |
| Thư mục con trong docs | Không đọc lại ở lần này | `agents/openai.yaml` (tuỳ chọn); phần còn lại không đọc lại ở lần này | `scripts/` `examples/` `resources/`; Studio giữ thêm `references/` `assets/`, chưa chạy thật |
| Giới hạn danh sách skill | `description` + `when_to_use` cắt ở 1 536 ký tự | ≤2 % ngữ cảnh / 8 000 ký tự; `[codex 0.147, mã]` 1 024 ký tự / 8 000 B (máy này 0.163.0, chưa đọc lại mã) | Không thấy số trong docs đã đọc |

**Quyết định:** Canonical Skill trong `skills/`; config theo agent nằm ngoài hoặc được sinh; lệnh `studio.py install` copy vào nơi agent có discovery. Đừng giả định symlink hay permissions của agent A tự hoạt động trên agent B. Gọi Codex hoặc Antigravity thật: `not_run:needs-directive`.

## Nạp file luật

Một nguồn chuẩn để soạn thảo không đồng nghĩa mọi agent ưu tiên file như nhau; policy và permission của host luôn có quyền riêng, Markdown của repo không thay được chúng.

| Agent | File luật của repo | Cách nạp |
|---|---|---|
| Claude Code | `CLAUDE.md` | nhập `@AGENTS.md` (cú pháp import được docs Claude xác nhận) |
| Codex | `AGENTS.md`, `AGENTS.override.md` | từ root tới CWD; file gần CWD ghi đè file rộng hơn, dưới giới hạn budget |
| Antigravity | `AGENTS.md`; `GEMINI.md` trỏ về `AGENTS.md`; `.agents/rules/` theo docs | xem rule discovery, paths, activation mode của đúng phiên bản |

- Không đặt `CLAUDE.md` hay `GEMINI.md` làm tên giả cho Codex: Codex không tự đọc những tên đó nếu không có fallback config.
- Cái gì được tự đọc: file luật của repo theo discovery của runtime, không mặc định chung; `SKILL.md` chỉ khi skill được chọn hay gọi; `references/` khi `SKILL.md` chỉ đúng file; `scripts/` không tự chạy, agent phải gọi tool; `assets/` khi tác vụ dùng; `evals/` không phân phối cùng skill; `standards/` là tài liệu tác giả, không chèn vào runtime.
- Dự án mới: (1) chép `templates/starter-project/`; (2) chỉ đặt nguyên tắc thường trực và ngắn, quy trình phức tạp đưa vào skill; (3) cài skill bằng `studio.py install`; (4) hỏi agent «Which repo instruction files and Skill names are active?» rồi kiểm thực tế; (5) đổi phạm vi thì test trong phiên mới.

**Nguồn:** [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Claude Code Memory](https://code.claude.com/docs/en/memory), [Claude Skills](https://code.claude.com/docs/en/skills), [Antigravity Rules](https://www.antigravity.google/docs/rules/).

## Claude Code

Checked: 2026-10-23 · nguồn đã mở lại: [Official Skills](https://code.claude.com/docs/en/skills) (đích cài, danh sách khoá frontmatter, giới hạn danh sách skill). [Official Memory](https://code.claude.com/docs/en/memory) và [Official Hooks](https://code.claude.com/docs/en/hooks): `not_run:chưa mở lại` ở lần này, phần liên quan giữ nguyên văn bản cũ, kiểm lại trước khi dựa vào.

Chỉ áp dụng khi chạy **Claude Code**. Portable `SKILL.md` không được tùy tiện mang `hooks`, `disable-model-invocation`, `context`, `agent`, `paths`, `background`, model/effort hay dynamic injection sang Codex/Antigravity.

- Project Skills: `.claude/skills/<skill-name>/SKILL.md`.
- User Skills: `~/.claude/skills/<skill-name>/SKILL.md`. Lệnh `install --user` của Studio **không hỗ trợ** đích này (`--agent claude --user` thoát 2, `ERROR: --user is not supported for claude; use --workspace`); muốn cài cấp người dùng thì tự chép thư mục vào đó.
- Project instructions: `CLAUDE.md`, có thể tham chiếu chung `@AGENTS.md`; nhập một file đồng nghĩa file đó được nạp vào context, không tiết kiệm token nếu luôn import.
- Rules thường trực theo file: `.claude/rules/*.md` (scoped khi tính năng hỗ trợ).
- Hook trong Skill frontmatter có lifecycle từ khi invoked; guardrail tổ chức bắt buộc phải cấu hình cấp cao hơn ở runtime/policy. Không cho rằng `hooks` chỉ là đề xuất văn bản: nó là code trigger, nên review script và test hành vi allow/block trước khi publish.
- Không auto-install khi chỉ clone repo: `skills/` là canonical source; project discovery thuộc `.claude/skills/`.

Frontmatter portable (đưa được sang Claude Code, claude.ai, Codex, Antigravity):

```yaml
---
name: audit-my-data
description: "Audits tabular data. Use when checking dataset completeness, keys and null rates."
metadata:
  version: "1.0.0"
---
```

Chỉ Claude Code, khi người dùng chủ động chọn tính năng này:

```yaml
---
name: deploy-preview
description: "Deploys a preview build. Use when explicitly asked to deploy a preview environment."
disable-model-invocation: true
# hooks: phải kiểm tra event/matcher/hook schema thực tế theo version
---
```

- Sau compaction, Claude có thể chỉ tái gắn phần đầu của Skill (docs nêu first 5,000 tokens mỗi Skill). Đưa safety và Definition of Done lên đầu; không nhầm với gợi ý 500 dòng.
- Dùng `description` để phát hiện; thân được đọc khi Skill invoked. `context: fork`/subagent và `${CLAUDE_SKILL_DIR}` là Claude-specific, không gửi raw sang runtime khác.
- Skill phải chuyển qua claude.ai hay Skills API thì chỉ dùng sáu khoá portable: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`.

**14 khoá chỉ có ở Claude Code** (ngoài sáu khoá portable; Studio giữ cùng 14 khoá trong `CLAUDE_CODE_KEYS`): `when_to_use`, `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `disallowed-tools`, `model`, `effort`, `context`, `agent`, `background`, `hooks`, `paths`, `shell`. Mặc định (`--target portable`) `validate` báo lỗi `FM4` cho từng khoá; với `validate <skill> --target claude-code` chúng chỉ là cảnh báo `FM6` ("Claude Code only; claude.ai và API từ chối khoá này bằng lỗi cứng"). Skill chỉ chạy trong Claude Code thì dùng `--target claude-code`; skill portable giữ mặc định.

**Giới hạn danh sách skill:** docs cắt `description` cộng `when_to_use` ở 1 536 ký tự; đặt ý «dùng khi nào» lên đầu. Chuẩn Studio chặt hơn (`description` ≤1 024 ký tự, SK-00) nên bám chuẩn Studio.

**Kiểm tĩnh:** `claude plugin validate <thư mục> --json` chỉ để ghi nhận, không làm cổng cho skill; cổng của plugin là `tests/test_plugin_validate.py`, chạy cục bộ khi máy có `claude`. Lần chạy 2026-10-23 trên `.claude/skills` vừa cài: exit 0, `success: true`, `contents: []`.

**Nguyên tắc:** không copy cấu hình Claude thành portable `SKILL.md`; giữ base Skill chung và tạo variant khi tính năng riêng là cần thiết.

## Codex

Checked: 2026-10-23 · nguồn đã mở lại: [Build Skills](https://learn.chatgpt.com/docs/build-skills) (đích cài, `agents/openai.yaml`, giới hạn danh sách). [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md): `not_run:chưa mở lại` ở lần này. Phiên bản Codex trên máy chạy kiểm: `codex-cli 0.163.0`.

- Repo/project: `.agents/skills/<skill-name>/SKILL.md` ở thư mục làm việc và mỗi thư mục cha tới gốc repo.
- User scope: `~/.agents/skills/<skill-name>/SKILL.md`. Docs còn nêu skill quản trị `/etc/codex/skills` và skill hệ thống đi kèm Codex (Studio không cài vào đó). `install --agent codex --user` chép vào `~/.agents/skills/<tên>`, và `~/.agents` phải có sẵn (thiếu thì thoát 2, không tạo gì).
- Skills được chọn bởi explicit hay implicit invocation; trong Codex có `$skill-name`, `/skills` theo hỗ trợ hiện hành.
- Codex và Antigravity cùng dùng `.agents/skills/` trong project. Không copy cùng skill hai lần thành tên khác nhau vì chúng sẽ cạnh tranh trigger.
- Danh sách skill nạp ban đầu dùng tối đa 2 % cửa sổ ngữ cảnh của model, hoặc 8 000 ký tự khi chưa biết cỡ cửa sổ; chỉnh được bằng `skills.max_context_tokens`, trần 10 000 token.
- `[codex 0.147, mã]`: mỗi `description` 1 024 ký tự, thân `SKILL.md` 8 000 byte (Studio báo `ST3` WARN khi thân vượt). Máy này đang chạy `codex-cli 0.163.0`, khác 0.147: **chưa đọc lại mã** ở 0.163.0, hai con số này chưa xác nhận cho bản đó.
- Portable manifest (`name`, `description` và optional fields theo Agent Skills) được ưu tiên. `agents/openai.yaml` là file tùy chọn cho **UI metadata, invocation policy, dependency information** của ChatGPT/Codex; không bắt buộc, chỉ thêm khi dự án thực sự cần. Mẫu đầy đủ (`new --full`) có `agents/openai.yaml` ghi rõ "Optional, Codex only; delete if unused".
- Không áp dụng Claude Code `hooks` YAML vào Codex. Sandbox/approvals và tính năng policy cần cấu hình riêng theo Codex version và product surface.
- `SKILL.md` mô tả target/action/validation, không có quyền tự cấp authorization. Scripts cần chạy với cwd/path đúng; đừng copy absolute path ở máy tác giả. Việc phá hủy hoặc publish cần action plan, reviewer và permissions tương ứng, không dựa vào việc model hứa tuân thủ.
- **Không nhầm lẫn:** Skill package dùng `SKILL.md`, còn `AGENTS.md` là persistent project instructions; hai thứ phục vụ mục tiêu khác nhau.

## Antigravity

Checked: 2026-10-23 · nguồn đã mở lại: [Official Skills](https://antigravity.google/docs/skills) (đích workspace và toàn cục, thư mục con). [Official Rules](https://www.antigravity.google/docs/rules/): `not_run:chưa mở lại` ở lần này. Product name trong tài liệu công khai là **Google Antigravity**; "AntiCraft" không phải tên chính thức được xác minh.

- Project/workspace Skills: `.agents/skills/<skill-name>/SKILL.md`. Legacy `.agent/skills` còn có thể tương thích, nhưng repo mới nên dùng `.agents/skills`.
- Global Skills (App và IDE): `~/.gemini/config/skills/<skill-name>/SKILL.md`. Tài liệu nêu CLI dùng đích khác, `~/.gemini/antigravity-cli/skills/<skill-name>/`; lệnh `install --user` của Studio **không** ghi vào đích CLI này. `install --agent antigravity --user` chép vào `~/.gemini/config/skills/<tên>`; `~/.gemini/config` phải có sẵn (thiếu thì thoát 2, không tạo gì).
- Luật workspace: `AGENTS.md` là bản nguồn; `GEMINI.md` trỏ về `AGENTS.md` (mẫu `templates/starter-project/`); `.agents/rules/*.md` tùy surface và activation configuration. Rules cần load thường xuyên đặt ở `AGENTS.md` hay `.agents/rules/`; workflow dùng lại đặt trong Skills, không giữ song song workflow cũ và Skill cùng tên khi migrate.
- Nếu đã cài Skill tại `.agents/skills` bằng Codex, không cần cài lại để Antigravity đọc cùng dữ liệu; kiểm tra behavior trên surface được dùng.
- Thư mục con: tài liệu liệt kê `scripts/`, `examples/` và `resources/` bên cạnh `SKILL.md`; không thấy nhắc `references/` hay `assets/`. Studio giữ `references/` và `assets/` (SK-01) và `install` chép nguyên cây thư mục. Chưa có bằng chứng chạy thật là Antigravity đọc `references/` hay `assets/` (`not_run`); cần `examples/` hoặc `resources/` thì tạo thêm theo docs.
- Không sao chép frontmatter `hooks` hay `${CLAUDE_SKILL_DIR}` từ Claude Code. Permission và tool approval theo Antigravity runtime đang dùng; tên rule file không đủ làm security boundary. Với UI/IDE, vị trí cài global hay plugin có thể khác CLI: kiểm tra docs theo surface và version.
- **Migration cần re-check:** tài liệu migration công khai từng hiển thị thời hạn ngừng legacy workflows khác nhau giữa host `antigravity.google` và `www.antigravity.google`. Repo này không tuyên bố ngày deadline tuyệt đối; xác minh documentation version, CLI/IDE version và thử migration trước khi tắt workflows cũ. Đọc: [Migration docs](https://www.antigravity.google/docs/migration/workflows-to-skills/).

## Cài và kiểm thử nhanh

```bash
mkdir -p ./target-project   # --workspace phải là thư mục có sẵn, thiếu thì thoát 2
python3 studio.py install skills/skill-creator-studio --agent claude --workspace ./target-project
python3 studio.py install skills/skill-creator-studio --agent codex --workspace ./target-project
python3 studio.py install skills/skill-creator-studio --agent antigravity --workspace ./target-project
# cấp người dùng (Claude không hỗ trợ)
python3 studio.py install skills/skill-creator-studio --agent codex --user
python3 studio.py install skills/skill-creator-studio --agent antigravity --user
```

Sau khi cài: Claude Code kiểm tra `/skill-creator-studio` có tìm được; Codex gọi `$skill-creator-studio` hay liệt kê `/skills`; Antigravity dùng yêu cầu tương ứng hoặc slash-command nếu surface hỗ trợ.

Kiểm thử chung: chạy positive và negative trigger trong phiên mới; chạy 3 prompt của `evals/<name>/cases.json` có và không có Skill; thử Skill với fixture synthetic và xác minh input, output; việc có side-effect thì test permission deny và allow trong sandbox mock, không dùng payment hay deploy thật.

- **Claude Code:** `/context` xác nhận `CLAUDE.md` được nạp và `@AGENTS.md` không bị bỏ qua; Skill chỉ người dùng được gọi thì xác minh không auto-invoke; test hook deny và allow chỉ trên sandbox mock.
- **Codex:** chạy agent từ repo root, xác nhận `AGENTS.md` đọc đúng, không bị local override; dùng `/skills` hoặc `$skill-creator-studio` để kiểm explicit invocation; test packaging không mang `evals/` theo; kiểm lại sandbox/approvals trước mỗi automated deployment.
- **Antigravity:** kiểm tra `.agents/skills/` được indexed và tên Skill hiện diện; `AGENTS.md` và `GEMINI.md` được nhận diện, nội dung không trái nhau.
