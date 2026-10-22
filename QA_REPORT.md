# QA Report — Agent Skill Studio v0.1.0

**Run date:** 2026-10-23 · **Status:** PASS (kiểm tĩnh offline, unit test, và một lô kích hoạt trên Claude Code) · **Base:** nhánh `sprint/spr-33-skill-standard`, HEAD `ccbff43` (TK1–TK12) cộng thay đổi tài liệu TK13. Lệnh chạy trên bản `git archive` của cây đã chốt (kết thúc dòng LF), Python `-X utf8`.

## Validation results

- `python -X utf8 studio.py validate --all --require-evals` — **PASS**: `skill-creator-studio` and `data-quality-audit` have **0 ERROR, 0 WARN**.
- `python -X utf8 studio.py evals --all` — **PASS**: mỗi bộ `cases.json` có **8 case** (5 nên kích hoạt, 3 near-miss không nên), gồm positive và negative. Lệnh này chỉ kiểm schema, **không chạy model**.
- `python -X utf8 studio.py sync-template --check` — **PASS**: `Template distribution mirror is in sync.` (hai template `skill-template` và `skill-template-full` khớp từng file với bản trong skill factory).
- `python -X utf8 -m pytest tests -q -p no:cacheprovider` — dòng cuối nguyên văn:

  `339 passed, 1 skipped, 1 warning, 48 subtests passed in 24.53s`

- `python -X utf8 -m unittest discover -s tests` — **PASS**: `Ran 340 tests`, `OK (skipped=1)`. (`unittest` in `UnicodeDecodeError` từ thread subprocess cp1252 nhưng vẫn exit 0; có từ trước sprint.)
- `python -X utf8 -m pytest tests/test_docs_links.py -q -p no:cacheprovider` — **PASS**: `1 passed`.
- `python -X utf8 studio.py fmt --check standards/README.md templates/README.md` — **PASS**: exit 0, `2 files, 0 changed`.
- `studio.py package` — **PASS**: ZIP chạy được cho cả hai skill mẫu; `evals/` và `__pycache__` bị loại.

## Lô kích hoạt SPR-33 (Claude Code, 22/10/2026)

- Công cụ: Claude Code **2.1.308**, model `claude-sonnet-5-5`, 16 lượt, 16/16 `ran`, 0 `not_run`. Nạp skill qua `--plugin-dir` từ bản `git archive` tại SHA lô `6d47a330224b7e01a54a330f08a24f9c5cc51729`, `skill_sha256_loaded` khớp băm cây skill tại SHA đó.
- Kết quả đếm bằng `evals/tools/activation.py summarize`: `data-quality-audit` positive **5/5**, negative **0/3**; `skill-creator-studio` positive **3/5**, negative **0/3**. Số đo trên mẫu nhỏ, không kết luận skill tốt hay kém.
- Log: `evals/<skill>/runs/SPR-33/`. Hồ sơ đo và transcript đã che: `sc7-runs.md` trong hồ sơ sprint ở OpcOS (`system/docs/plans/2026-10-22-skill-studio-standard-v1/evidence/`).
- `not_run`: Codex và Antigravity **thật** (cần chỉ thị của Đức, `not_run:needs-directive`); `claude plugin eval` (`not_run:needs-model-call`). `model_evaluated` giữ **`false`** cho cả hai skill (`registry/catalog.json`).

## Đa agent (kịch bản mục 9.14, bản chạy 2026-10-23)

- `codex` và `antigravity`: `new --lang vi` → `validate` → `package` → `install --workspace` đều exit 0 với tên `demo-codex`, `demo-antigravity`. `--workspace` phải là thư mục có sẵn (thiếu thì thoát 2).
- `claude`: tên `demo-claude` bị `FM5` chặn (tên không được chứa "claude"), nên `validate`, `package`, `install` exit 1; đây là validator hoạt động đúng. Với tên hợp lệ `demo-cc` bốn lệnh exit 0 (TK13 kiểm tay; bảng QA chính thức ở `multi-agent.md` trong hồ sơ sprint).
- `install --user` (HOME tạm): `codex` và `antigravity` exit 0 khi thư mục cha có sẵn, exit 2 khi thiếu; `claude --user` exit 2. `claude plugin validate` trên `.claude/skills` đã cài: exit 0, `contents: []`, chỉ ghi nhận.
- `codex --version` = `codex-cli 0.163.0`, khác `[codex 0.147]` nên các con số đọc từ mã Codex 0.147 **chưa đọc lại**.

## Quality and evidence limits

- Chưa có lượt chạy thật nào trên Codex hay Antigravity ở sprint này; hoạt động kích hoạt và chất lượng chéo mô hình **chưa được xác minh** ngoài lô Claude Code ở trên và log SPR-18.
- Rules SK-03/04/06/07/08/10/12 require semantic review and/or model/runtime tests, beyond offline CLI lint.
- Model baselines are explicitly `NOT RUN`; do not call the Skills production-certified until acceptance tests and owner approval are completed.
- License: MIT, decided by the owner on 2026-10-12 (see `LICENSE` and `LICENSE_POLICY.md`).

## Release decision

**Suitable as a functional starter repository and static skill-building factory. Not yet production-certified for any runtime or high-impact operation.**
