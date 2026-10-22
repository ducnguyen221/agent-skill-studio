# Evaluation Standard — Cách chứng minh Skill hoạt động

## Contents
- Phạm vi và nơi lưu
- Loại bài kiểm thử
- Thiết kế test cases
- Cách chạy baseline và A/B
- Release gate nội bộ
- Log test nên có
- Không pass giả (`not_run`)
- Phân vai hai hệ eval
- Xuất sang agentskills
- Cách reviewer đánh giá

## Phạm vi và nơi lưu

**Mặc định Studio:** `evals/<skill-name>/cases.json`, `rubric.md`, `fixtures/`, `baselines/`, `runs/` (runs có thể tạo khi thực thi, không phải bằng chứng có sẵn). Repo giữ bộ test; package runtime Skill **không chứa evals**.

Nếu một Skill độc lập không có repo, có thể colocate evals bên trong folder Skill; phải exclude khi publish và ghi rõ trong packager. Không trộn private fixtures vào `assets/` phát hành.

## Loại bài kiểm thử

| Loại | Cần xác minh | Công cụ |
|---|---|---|
| Structural | Frontmatter, paths, references, thông số | `studio.py validate` |
| Trigger positive | Request thuộc phạm vi làm Skill kích hoạt | Fresh-session Claude/Codex/AGY |
| Trigger negative | Request ngoài phạm vi không kích hoạt | Fresh-session Claude/Codex/AGY |
| Execution | Agent đọc đúng references, chạy đúng scripts, hoàn thành steps | Agent logs/observation |
| Output quality | Data, code, content đạt rubric | Deterministic script + human/model grader phù hợp |
| Safety | Thao tác không có approval bị chặn | Permission sandbox/hook dry-run |
| Regression | Phiên bản mới không kém bản cũ trên test quan trọng | A/B logs và review |
| Context/cost | Mức dùng token/time đủ hiệu quả | Telemetry có điều kiện, không ước đoán |

## Thiết kế test cases

`cases.json` là **Studio-owned evaluation manifest** (không tuyên bố tương thích runner của vendor nào). Mỗi case có `id`, `prompt`, `should_trigger` (boolean), `expected_behaviors` (array non-empty), `quality_criteria`, và tùy chọn `fixtures`. Giữ ít nhất 3 tình huống thật và ít nhất một negative case; nên thêm edge cases và high-risk case nếu có.

**Dữ liệu test**: chỉ dùng synthetic/public, không đưa secrets. `expected_behaviors` phải có kết quả có thể quan sát, như `measure uses DATEADD with appropriate date table assumption`, không viết "agent is smart".

## Cách chạy baseline và A/B

1. Chọn >=3 bài test. Ghi task, version, model, runtime, dữ liệu đầu vào, rubric trước khi viết Skill.
2. Chạy prompt **không có Skill** trong phiên mới; chấm kết quả bằng rubric, lưu baseline.
3. Chạy prompt tương đương **có Skill** trong phiên mới; chấm các tiêu chí và ghi file đã đọc/scripts đã chạy.
4. Lặp trên model thực sử dụng. Với Skill mission-critical, test đủ các model/runtime sản xuất; với Skill thông thường có thể ưu tiên model phổ biến.
5. So sánh pass/fail, false trigger, blocked actions, chất lượng, chi phí thực nếu đo được; quyết định Keep / Refine / Roll back.
6. Khi bỏ một rule bị cho là dư thừa, test version có và không có rule để tránh regression.

## Release gate nội bộ

- **Prototype:** static checks pass và đã có evals template, được dùng thử nội bộ với nhãn prototype.
- **Candidate:** >=3 scenarios, 1 negative, baseline ghi nhận (hoặc justified unavailable), các nguồn tài liệu đã review, script smoke test pass.
- **Production:** dữ liệu từ phiên test thực tế trên các runtime mục tiêu; kết quả đạt rubric; không có safety-critical failure; owner signoff và rollback.

Chưa chạy model: xem [Không pass giả](#không-pass-giả-not_run). Không đặt ngưỡng chất lượng phần trăm phổ quát; mỗi skill xác định hard acceptance riêng tại `rubric.md`.

## Log test nên có

```json
{
  "case_id": "creator-positive-new",
  "skill_version": "0.1.0",
  "runtime": "claude-code",
  "model": "<actual model ID>",
  "run_at": "<ISO date-time>",
  "with_skill": true,
  "observed_files": [],
  "score": null,
  "status": "not_run",
  "evidence": "<path to session log or screenshots if run>"
}
```

## Không pass giả (`not_run`)

- Chưa chạy model thì ghi `not_run`; không gọi Skill là production-tested.
- Một agent tự nhận đã pass mà không có log hay artefact thì không tính. Static JSON validator chỉ chứng minh metadata của case hợp lệ, không chứng minh model đã hoàn thành case.
- Trong log chạy, giữ trường `null` và `status: "not_run"` cho đến khi có test thật; không tự điền score hay pass.

## Phân vai hai hệ eval

- RED/GREEN của `writing-skills` (agent-agile-team): kiểm áp lực hành vi.
- A/B của Studio (mục "Cách chạy baseline và A/B"): kiểm kích hoạt và chất lượng đầu ra.

## Xuất sang agentskills

`studio.py evals <skill> --export agentskills` ghi `evals/<skill>/cases.json` sang định dạng agentskills theo ánh xạ SPEC mục 9.6 của SPR-33 (`system/docs/plans/2026-10-22-skill-studio-standard-v1/SPEC.md` trong repo OpcOS). Bộ xuất: TK8 — lệnh chưa có trong bản này.

## Cách reviewer đánh giá

- Prompt kích hoạt đúng? Không kích hoạt sai?
- Agent có bỏ qua reference thiết yếu?
- Có chạy script khi đáng lẽ run, hay chỉ đọc mô tả?
- Có tuyên bố kết quả khi chưa kiểm tra?
- Có lỗi hệ thống vì Skill quá dài hoặc model over-guided?
- Với output dạng file, mở và kiểm tra file thật, không chỉ xem transcript.

**Nguồn:** [Anthropic Skill Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices), [Claude Code Skills evaluation](https://code.claude.com/docs/en/skills), [Agent Skills evaluation](https://agentskills.io/skill-creation/evaluating-skills). Studio tách evals là quyết định thiết kế nội bộ.
