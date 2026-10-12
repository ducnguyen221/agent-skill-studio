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
  runs/                   # tạo trong lần thực thi thực tế (optional)
```

## Trước khi viết Skill

1. Chọn >=3 prompts thực tế: một typical, một edge, một negative trigger (không nên gọi Skill).
2. Ghi expected behavior và criteria **trước** khi viết nội dung Skill dài.
3. Chạy không Skill để có baseline, tốt nhất phiên mới; nếu không chạy được, ghi `not_run` thay vì giả kết quả.

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
