# Evals Runbook — kiểm định Skill bằng model thật

## Vì sao evals tách khỏi Skill?

Evals là các bài kiểm thử, rubric, dữ liệu thử và log no-skill baseline, **không phải hướng dẫn thường trực của agent**. Studio mặc định lưu tại repo-root `evals/<skill-name>/`, để tránh phát hành đáp án test hoặc private fixtures khi đóng gói Skill. Đây là lựa chọn thiết kế của Studio, không phải luật bắt buộc của Agent Skills.

## Cấu trúc một bộ eval

```text
evals/<skill-name>/
  cases.json              # prompt, should_trigger, expected_behaviors, fixtures
  rubric.md               # tiêu chí chấm độc lập, hard-fail điều kiện
  fixtures/               # dữ liệu synthetic, không có customer data
  baselines/BASELINE.md   # No-skill run, nếu chưa chạy ghi NOT RUN
  runs/                   # tạo trong lần thực thi thực tế (optional); lô có tên: runs/SPR-18/, runs/SPR-33/
```

Công cụ chung nằm ở `evals/tools/` (chỉ thư viện chuẩn): `activation.py` đếm kích hoạt từ transcript (`verify`, `hash`, `count`, `freeze`, `summarize`), `oracle.py` chấm đầu ra theo `expected/<case-id>.json`, `redact.py` làm bản transcript che email và đường dẫn máy để commit được.

Xuất các ca positive sang định dạng agentskills (không gọi model): `python3 studio.py evals <skill> --export agentskills --out dist/agentskills` ghi `<out>/<skill>/evals/evals.json`; `--out` không được nằm dưới `skills/` hay `evals/`.

## Trước khi viết Skill

1. Chọn >=3 prompts thực tế: một typical, một edge, một negative trigger (không nên gọi Skill).
2. Ghi expected behavior và criteria **trước** khi viết nội dung Skill dài.
3. Chạy không Skill để có baseline, tốt nhất phiên mới; nếu không chạy được thì không bịa kết quả — định nghĩa: [Không pass giả](../standards/EVALUATION_STANDARD.md#không-pass-giả-not_run).

## Khi chạy với Claude, Codex hoặc AGY

1. Chọn runtime, exact model/version, tool availability và workspace permissions.
2. Chạy lần 1 trong **fresh session, Skill không có mặt/disable đúng cách**. Lưu prompt, output và log.
3. Chạy lần 2 trong **fresh session, có Skill**; quan sát activation, files read, scripts executed, permission prompts và output thật.
4. Dùng `rubric.md` chấm từng tiêu chí và so với baseline. Với side-effect phải dùng mock/staging.
5. Ghi file `runs/<ISO-UTC>_<runtime>_<case-id>.json` cùng đường dẫn evidence/screenshot/session log.
6. Nếu yếu hơn baseline hoặc fail safety -> REFINE, test lại; đừng chỉ thêm một đoạn "must always".

## Mẫu run log

```json
{
  "case_id": "creator-new-skill",
  "timestamp": null,
  "runtime": null,
  "model": null,
  "with_skill": null,
  "triggered": null,
  "observed_files": [],
  "observed_scripts": [],
  "rubric_result": null,
  "status": "not_run",
  "evidence_path": null
}
```

## Static checker và giới hạn

`python3 studio.py evals --all` kiểm tra cấu trúc `cases.json`: 3+ case, 1 positive +1 negative, `expected_behaviors`, local fixture paths; **không gọi các model** và không chấm kết quả. Chỉ nâng trạng thái lên production-tested khi có log thực tế trên những runtimes được sử dụng.

## Bảo mật

Không upload dữ liệu production, tokens, email cá nhân hoặc thông tin khách hàng vào fixtures công khai. Với dữ liệu thật, lưu ở kho riêng có permission và trỏ test qua fake fixture/anonymized data.

## Lô SPR-18 — phiên mới có/không skill, đếm kích hoạt từ transcript

Bộ câu, oracle (`expected/`), thước (`rubric.md`) và `runs/SPR-18/manifest.json` đã đóng băng; sửa một file đóng băng thì `activation.py verify` báo.
Mỗi skill có 8 case: 5 positive (`typical` 2, `edge` 2, `input-error` 1) và 3 `near-miss`. Chỉ đo kích hoạt bằng `evals/tools/activation.py`
(đếm lời gọi tool Skill hoặc lần đọc `…/<skill>/SKILL.md` của agent; không quét system prompt, nên tên skill trong danh mục không tính).

Kiểm trước mỗi lô:

```text
python -X utf8 evals/tools/activation.py verify --eval-dir evals/<skill> --main-skill-dir <OpcOS>/plugins/agent-skill-studio/skills/<skill> --cache-skill-dir <~/.claude>/plugins/cache/agent-skill-studio/agent-skill-studio/0.1.0/skills/<skill> --manifest evals/<skill>/runs/SPR-18/manifest.json
python -X utf8 evals/tools/activation.py hash <thư mục skill>          # băm cây skill, đã chuẩn hoá CRLF
python -X utf8 evals/tools/activation.py count <transcript.jsonl> --skill <skill> --runtime claude-code|codex
python -X utf8 evals/tools/activation.py summarize evals/<skill>/runs/SPR-18
```

Đo thật (17/10/2026) — `runs/SPR-18/harness-status.json` và `runs/SPR-18/smoke/*`:

| Harness | Kết luận | Cách chạy |
|---|---|---|
| Claude Code | **go** | `claude -p --model claude-sonnet-5-5 --output-format json --permission-mode acceptEdits --allowedTools "Skill,Read,Glob,Grep,Write,Edit,Bash(python:*),Bash(python3:*),Bash(py:*),Bash(ls:*),Bash(cat:*)" --disallowedTools "WebFetch,WebSearch"` đọc prompt từ stdin, cwd là thư mục chạy sạch dưới `~/OpcOS/workspaces/spr18-eval/claude-code/<run-id>/`. Có skill: plugin bật sẵn. Không skill: thêm `--settings '{"enabledPlugins":{"agent-skill-studio@agent-skill-studio":false}}'` (tắt theo tiến trình, không đổi cài đặt máy; phép thử vắng skill sạch: transcript không còn nhắc tên skill nào). `claude -p` chạy lồng được. Transcript: `~/.claude/projects/<cwd-slug>/<session_id>.jsonl`. Plugin nạp từ thư mục nguồn marketplace, không phải cache — checkout nguồn phải đứng yên trên `main`. |
| Codex | **go** (baseline cần cửa sổ tắt plugin, xem cuối dòng) | `ask-codex ask --origin human --access workspace --cwd <run-dir> --model gpt-6-luna`, prompt qua stdin; skill đưa vào bằng `studio.py install <skill> --agent codex --workspace <run-dir>`. Baseline: Codex bật plugin `agent-skill-studio` toàn máy nên phiên không-skill vẫn thấy cả hai skill (smoke 17/10 hỏng); chưa có đường tắt theo tiến trình qua cầu. Cách đã dùng 18/10: khi không có phiên Codex tương tác, tắt plugin bằng `codex-config.ps1 -Set 'plugins."agent-skill-studio@agent-skill-studio".enabled=false'` trong đúng một cửa sổ lô, chạy smoke vắng skill (`smoke/codex_base_clean.json`) rồi 5 phiên, bật lại `=true` trong `finally`, so băm file config trước/sau. Cần Đức duyệt mỗi lần. Transcript: `~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-*-<id>.jsonl`, tìm theo `cwd` ở dòng đầu. |
| Antigravity | **no-go** (`no-go:no-transcript;global-skill-root-not-isolated`) | `ask-agy` headless không sinh transcript, và liệt kê cả skill chưa cài vào workspace (lấy từ `~/.gemini/antigravity/skills`) nên không tách được có/không skill. |

Lưu ý khi chạy: dưới `--allowedTools` ở trên, lệnh Bash ghép (`cd … && ls … && python …`) bị từ chối; model tự chạy lại từng lệnh. Codex ghi cảnh báo
"Exceeded skills context budget": danh mục skill chỉ còn tên. Câu trả lời của cả hai harness theo tiếng Việt vì luật toàn cục của máy nạp vào phiên (ghi vào `preamble`).

### Schema log một phiên (`runs/SPR-18/<ISO>_<runtime>_<case-id>_<with|base>.json`)

Giữ các khoá mẫu cũ và thêm: `pair_id` (`<skill>/<case-id>/<runtime>`), `with_skill`, `kind`, `triggered`, `activation_evidence` (`hits`, `scripts`,
`transcript_sha256`), `transcript_path`, `cwd`, `skill_sha256_loaded`, `skill_sha256_repo`, `pinned_model`, `actual_model`, `preamble`, `ledger_id`,
`status` ∈ `ran` | `not_run` | `contaminated` | `invalid-version` | `invalid-model`. Transcript đầy đủ không nằm trong repo này mà ở hồ sơ sprint
của OpcOS; log chỉ giữ `hits` và băm.

Lô SPR-33 ghi thêm năm khoá (đọc được từ log mẫu; `activation.py verify|summarize` không dùng chúng):

- `should_trigger`: kỳ vọng của bộ câu (`true` cho câu dương, `false` cho câu âm/near-miss), chép từ `cases.json`; so với `triggered` để tính dương/âm.
- `loading_mode`: cách skill vào phiên; `plugin-dir` = nạp bằng `--plugin-dir` từ cây `git archive` đã chốt (không dùng plugin cài sẵn của máy).
- `plugin_dir`: nguồn của cây plugin đó (thư mục thử và commit đã archive, `autocrlf=false`), viết dạng tương đối hoặc `~`, không đường tuyệt đối của máy.
- `session_id`: mã phiên `claude -p` (tên transcript `<session_id>.jsonl`); khi chạy không qua cầu A2A thì `ledger_id = session_id`.
- `not_run_reason`: lý do khi `status` khác `ran` (ví dụ chạm giới hạn phiên); khoá chỉ xuất hiện ở phiên không chạy, nên 16/16 log SPR-33 (đều `ran`) không mang khoá này.

## Antigravity — đo trong IDE (bàn giao cho sprint riêng RQ-117)

Cầu `ask-agy` (headless `--print`) không đo được kích hoạt: một lượt đo 17/10/2026 cho thấy (1) không có transcript (thư mục `brain/` không mọc thêm),
(2) danh mục skill lấy từ thư mục skill toàn máy chứ không từ workspace thử, nên không có baseline sạch. Muốn đo phải chạy phiên trong IDE.
Dùng lại nguyên bộ câu `evals/<skill>/cases.json`, oracle `expected/`, thước `rubric.md` (xem manifest), skill vào `.agents/skills` của workspace thử bằng
`studio.py install … --agent antigravity --workspace <run-dir>`, và với baseline phải tạm đưa skill toàn máy ra khỏi `~/.gemini/antigravity/skills`
(việc đổi máy, cần Đức duyệt riêng). Chấm kích hoạt bằng lịch sử tool call của IDE; không coi tên skill trong danh mục là kích hoạt.

## Lô SPR-33 — cùng cách đo, trên Claude Code

Lô 16 lượt (8 case mỗi skill) chạy ngày 22/10/2026 với Claude Code 2.1.308, model `claude-sonnet-5-5`, nạp skill bằng `--plugin-dir` từ bản `git archive` tại SHA lô, đúng lệnh ở dòng Claude Code của bảng trên; log ở `runs/SPR-33/`, đếm bằng `activation.py count … --runtime claude-code` và `summarize`. Số đo và giới hạn: [QA_REPORT.md](../QA_REPORT.md). Codex và Antigravity thật không chạy ở lô này (`not_run:needs-directive`).
