# Changelog

## 0.3.0 — 2026-10-29

Chặng 3 (agent-skill-studio:SPR-04): skill thứ hai `skill-curator`, lệnh `catalog`, `doctor` theo gói và ngân sách, `check` cho workflow và file luật, và đóng bảy nợ của chặng 2.

### Thêm

- Skill `skill-curator`: nhìn cả thư viện skill một lượt, chỉ đọc; đóng gói và cài riêng như `skill-creator-studio`.
- Lệnh `catalog`: một dòng mỗi skill nguồn (repo, phiên bản, băm cây, lỗi `doctor`, `model_evaluated`, khoá `metadata.opcos_*`); ra màn hình, JSON (`--json`, `--out`, schema `1`) hoặc `CATALOG.md` (`--md`).
- `catalog --installed claude,codex,antigravity` so bản đã cài với bản nguồn; `catalog --overlap` gắn nhãn cặp có thể trùng kèm bằng chứng và gợi ý cố định.
- `doctor --roots-from opcos` đọc gốc skill từ OpcOS và tìm skill theo manifest plugin; `--by-pack` gom theo gói; `--docs` kiểm tài liệu workflow và file luật; ngân sách chữ cho `--profile opcos`.
- Mã kiểm `WF1`–`WF4` (workflow), `RL1`–`RL4` (file luật) và `SEC` (secret) theo `standards/DOC_TYPES.md`.
- Site `docs/`: trang Cách dùng nói về `catalog` và skill `skill-curator`.

### Sửa

- `check` trên file có `type:` kiểm thật, thoát 0 hoặc 1 (trước đó thoát 2).
- `new` ở vùng cloud hoặc đường lạ báo `ERROR INPUT` thoát 1 thay vì ghi hay in traceback; `new --output` dưới `/tmp` trên macOS được phép.
- `standards/`: lý do cho «không tự sửa mọi WARN», mã `CT10` khớp luật `SK-14`, `DOC_TYPES.md` khớp máy kiểm; `CORE_RULES.md` sinh lại.

### Hợp đồng

| thay đổi | kiểu | trước → sau | bên dùng bị ảnh hưởng | tương thích ngược |
|---|---|---|---|---|
| lệnh `catalog` | thêm | — → `catalog [--roots-from opcos] [--roots …] [--installed …] [--overlap] [--json] [--out] [--md]`, schema JSON `1` | OpcOS `P11a`, `P11b`, SPR-10, SPR-11 | có |
| `doctor --roots-from opcos`, `--by-pack`, `--docs` | thêm | — → cờ mới; JSON thêm khoá `packs`, `docs`, `budget` khi có cờ hoặc profile | wrapper `P11a` | có (khoá mới chỉ thêm) |
| `doctor --profile opcos` ngân sách | sửa | không đo 350/8 000 → thêm WARN ngân sách và khoá `budget` | người chạy `--profile opcos`, `--fail-on warn` | không với `--fail-on warn` (thêm WARN có thể làm thoát 1) |
| `doctor` tìm skill theo manifest plugin | thêm | — → chỉ khi `--roots-from opcos` | wrapper `P11a` | có: `--roots`, `--roots-file` không đổi |
| `check` file workflow và luật | sửa | thoát 2 «not available yet» → kiểm thật, thoát 0 hoặc 1 | người chạy `check` trên file `type:`; CI repo khác | không (chặt hơn) |
| `catalog.json` `metadata.opcos_*` | thêm | — | Atlas SPR-11 | có |
| skill ship | thêm | plugin ship 1 → 2 skill (`skill-curator`) | người cài; `test-opcos.ps1` khối Studio; `registry.json`; junction Antigravity; bước `package` của CI | có |
| `new` vùng cloud hoặc đường lạ | sửa | ghi được hoặc traceback → `ERROR INPUT` thoát 1 hoặc lời báo | người chạy `new` | không (chặt hơn) |
| `new --output` dưới `/tmp` macOS | sửa | từ chối → cho phép | người dùng macOS | có (nới đúng chỗ) |
| phiên bản | sửa | `0.2.0` → `0.3.0` + tag | marketplace, cache | có |

### Nợ đóng

`RQ-013`, `RQ-019`, `RQ-024`, `RQ-026`, `RQ-029`, `RQ-030`, `RQ-031`.

## Chưa phát hành

- `docs/`: website 7 trang trên OpcOS Design System dùng chung (Trang chủ, Giới thiệu, Cài đặt, Cách dùng, Luồng & quy trình, Nguyên tắc, Docs); thư mục thứ bảy của repo, không vào gói phát hành. `tests/test_layout.py` khoá bảy thư mục thay vì sáu.

## 0.2.0 — 2026-10-28

Chặng 2 (agent-skill-studio:SPR-03): repo gọn sáu thư mục, luật nạp được cho ba agent, bằng chứng gọn mà cổng vẫn đếm lại được. Cộng cả mọi mục SPR-01, SPR-02 chưa phát hành bên dưới (ba chuẩn gộp vào `SKILL_AUTHORING_STANDARD.md` ở TK5 có lịch sử ngay trong mục TK5). **Đổi hợp đồng của bản này** (ai dùng bản `0.1.0` đọc kỹ):

| Thay đổi | Trước → sau | Ai bị ảnh hưởng | Tương thích ngược |
|---|---|---|---|
| Đường catalog đánh giá | `registry/catalog.json` → `evals/catalog.json`; đường cũ không đọc nữa | `studio_evals`, `studio.py`, test, fixture hợp đồng | Không |
| Bằng chứng đánh giá | `evals/<skill>/runs/<lô>/*.json` + `ab-<ngày>.json` → một file gọn `evals/<skill>/evidence/<lô>.json`; khối `evaluated` thêm khoá `evidence`, `ab_report` trỏ file gọn | cổng `model_evaluated`, `RUNBOOK.md`, `activation.py` | Không |
| Skill phát hành | plugin ship 2 skill → 1: `data-quality-audit` sang `examples/`, `content/` sang `examples/` | người cài plugin, CI, junction Antigravity | Không |
| `new --output` không `--eval-root` | eval ghi vào `<repo engine>/evals` → theo `--output` (`<cha>/evals` khi tên là `skills`, ngược lại `<output>/evals`); gốc ổ đĩa hoặc đường có link bị từ chối (thoát 2) | ca `new` dùng `--output` | Không |
| `new` khi file eval đã có | ghi đè → giữ, in `kept existing <đường>` | người chạy `new` lại | Có (chỉ bớt ghi) |
| `is_link` gặp `OSError` | `False` → `True` (từ chối, có báo) với mọi lỗi trừ không tồn tại / không phải thư mục | 23 nơi gọi | Không với đường không dò được |
| `check`/`validate`/`audit` trên thư mục có `SKILL.md` là symlink hoặc junction | đọc xuyên link → `ERROR INPUT`, thoát 1, không mở file | người chạy kiểm trên cây có link | Không |
| stderr khi cổng bị bỏ qua | im lặng → `note: model_evaluated gate skipped: installed engine (…)` ở `evals --all` của engine cài; `WARN: --all skipped <đường> (<lý do>); it is not checked` ở `validate --all` / `audit --all` | CI và người đọc stderr; mã thoát không đổi | Có (chỉ thêm dòng) |
| `fmt --all` | quét `tests/fixtures/`, `evals/*/fixtures/` → bỏ qua | CI, người chạy `fmt --all` | Có |
| File luật gốc | `CLAUDE.md` gốc giữ chỗ, trỏ `AGENTS.md`; `AGENTS.md`/`GEMINI.md` trỏ đường sống; `templates/project/` → `templates/starter-project/` nạp luật ba agent | người dùng Claude Code trong repo | Có |
| `VI5` | một mục tiếng Anh dài bị báo trong mọi thân Việt → không báo khi các mục có tỉ lệ chữ có dấu dưới 1 % chiếm quá 70 % chữ cái văn xuôi (`VI5_ENGLISH_BODY_SHARE`; code và bảng không tính) | skill thân chủ yếu tiếng Anh có nhãn Việt | Có (chỉ bớt báo) |
| README | 297 dòng hai ngôn ngữ → dưới 150 dòng, một `README.md` tiếng Việt | người đọc repo | Có |
| Phiên bản | `0.1.0` → `0.2.0` (`VERSION` của engine và ba manifest) + tag | marketplace, cache cài | Có |

- **agent-skill-studio:SPR-03 TK11 (chặng 2, `0.2.0`).** `VI5` bỏ báo theo mục khi các mục có tỉ lệ chữ có dấu dưới `VI5_ACCENT_MIN` (1 %) chiếm quá `VI5_ENGLISH_BODY_SHARE` (70 %) chữ cái văn xuôi (code và bảng không tính); thân Việt có một mục tiếng Anh dài, kể cả kèm khối code Anh dài, vẫn bị báo. README viết lại gọn (bỏ ghi chú dời cây cũ; giữ mục mã `INPUT`, `EV20` và bảng mã của engine; chi tiết `doctor`, `EX1`–`EX13`, `PACK` còn ở các mục SPR-01/SPR-02 dưới đây). Docstring `iter_md` nói đúng: với `--all` vẫn bỏ fixture, chỉ thư mục fixture được gọi đích danh mới đọc trọn. Test mới `tests/test_layout.py` (`test_six_top_dirs`, `test_no_file_deeper_than_three`, `test_no_runs_in_git`, `test_readme_short_one_language`) và hai test `VI5`. Bộ ca hợp đồng: 5 ca `*-version` và 5 ca `*-doctor-fixture-json` đổi `after` sang `0.2.0` (`studio_version`), `before` giữ nguyên.
- **agent-skill-studio:SPR-03 TK10 (`new` không ghi đè, eval theo `--output`).** `new` ghi `cases.json`, `rubric.md`, `baselines/BASELINE.md` bằng ghi độc quyền, đã có thì giữ; thư mục eval theo `--output`; từ chối gốc ổ đĩa và đường đi qua link; lỗi ghi được báo có mã.
- **agent-skill-studio:SPR-03 TK9 (`is_link` hỏng-đóng).** `ENAMETOOLONG`, `winerror 123`, `PermissionError` coi là link và mỗi nơi gọi báo có lý do; `doctor` không còn `realpath` trên đường không dò được. Engine cài trong `.claude`, `.agents`, `.codex`, `.gemini` bỏ qua cổng `model_evaluated` và in một dòng ra stderr (thoát không đổi); `validate --all` / `audit --all` nói skill nào bị bỏ qua; CI thất bại nếu cổng bị bỏ qua trên chính repo Studio.
- **agent-skill-studio:SPR-03 TK8 (đọc `SKILL.md` vùng cấm).** `check`/`validate`/`audit` trên thư mục chặn `SKILL.md` ở vùng cloud, secret, placeholder hoặc symlink bằng ERROR `INPUT` trước khi mở; `skill_dirs` không stat xuyên `SKILL.md` là symlink.
- **agent-skill-studio:SPR-03 TK7 (file luật gốc).** `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` trỏ đường tồn tại (test), thêm `doctor` và `fmt --check` trước khi báo xong; `tests/test_plugin_validate.py` chạy `claude plugin validate` và chấp nhận đúng một cảnh báo (`CLAUDE.md` ở gốc plugin) cùng `ICON_MISSING`.
- **agent-skill-studio:SPR-03 TK6 (`CORE_RULES.md` sinh từ chuẩn).** `skills/skill-creator-studio/references/CORE_RULES.md` sinh bởi `tests/gen_core_rules.py` từ `SKILL_AUTHORING_STANDARD.md` (đủ `SK-00`…`SK-15`, nguyên thân mỗi khối, kèm ưu tiên, vòng đời, Definition of Done); `SKILL.md` của skill trỏ về nó; test canh khớp.
- **agent-skill-studio:SPR-03 TK4 (`templates/starter-project/`).** `templates/project/` đổi tên `templates/starter-project/`; `AGENTS.md` là bộ luật chung duy nhất, `CLAUDE.md` nạp bằng `@AGENTS.md`, Codex đọc thẳng, `GEMINI.md` trỏ về; mỗi file có dòng `install` đúng cờ của engine.
- **agent-skill-studio:SPR-03 TK3 (`fmt --all` bỏ fixture).** `fmt --all` bỏ qua `tests/fixtures/` và `evals/*/fixtures/`, vẫn quét `examples/`; thư mục fixture gọi đích danh vẫn đọc trọn.


- **agent-skill-studio:SPR-03 TK5 (chặng 2, `standards/` 11 → 8 file; chưa phát hành).** **Đổi hợp đồng:** các đường `standards/CORE_STANDARD.md`, `RULES_AND_PRECEDENCE.md`, `SKILL_LIFECYCLE.md`, `ROBONUGGETS_46_RULE_MAP.md`, `MEMO-SKILL-V0.md`, `adapters/*`, `ECOSYSTEM.md`, `registry/*`, `QA_REPORT.md` không còn
  - **Gộp ba chuẩn vào `SKILL_AUTHORING_STANDARD.md`** (7 273 ký tự, trần +30 % so với 5 599): đoạn «Mức» (MUST / SHOULD / «MUST nếu …» của `CORE_STANDARD`, phiên bản 0.1.0 ngày 12/10/2026); mục «Ưu tiên khi luật mâu thuẫn» (từ `RULES_AND_PRECEDENCE`: policy host thắng Markdown, một luật một chỗ, `references/` chỉ chứa sự kiện); mục «Vòng đời» (từ `SKILL_LIFECYCLE`: bốn trạng thái Draft / Candidate / Production / Deprecated, luồng NEW → AUDIT → REFINE → RELEASE, PATCH / MINOR / MAJOR, AUDIT chỉ đọc). Các câu trùng với `SK-*` hoặc không còn đúng bỏ, mỗi câu có dòng trong bảng đối chiếu ở sổ OpcOS (`plans/2026-10-28-structure-rules-2/evidence/rule-map.md`). Số «13 rules» không còn: bộ luật là `SK-00`…`SK-15`.
  - `SK-05` thêm ý overlap giữa mô tả skill; `SK-07` thêm «xong = `check` đạt»; link `not_run` trỏ đúng mục `#không-pass-giả-not_run`; `SK-01`, `SK-09`, `SK-10` nhận ba câu của `CORE_STANDARD` (không tạo thư mục rỗng, script khai input / output / lỗi / dependency, không chép lệnh tự tắt xác nhận).
  - **Mới `DOC_TYPES.md`:** luật cho ba loại tài liệu (skill, workflow / quy trình, file luật agent) gồm cách nhận loại, phần bắt buộc, phần cấm, giới hạn độ dài. Chặng 3 cài máy kiểm theo file này.
  - **Mới `HARNESSES.md`:** gộp bốn file `adapters/` và bảng khả năng; giữ đủ 4 dòng `Checked: 2026-10-23`. Antigravity đọc `AGENTS.md`, `GEMINI.md` trỏ về `AGENTS.md` (cùng chữ với `templates/starter-project/`).
  - `EVALUATION_STANDARD.md` thêm mục «Khối evaluated» (bảng 8 khoá cổng đọc, ngưỡng đếm); `SECURITY_AND_PERMISSIONS.md` thêm frontmatter và luật «engine không nạp mã từ repo chứa nó» (bài học `LN3` của SPR-02); `SOURCE_TRACEABILITY.md` nhận bản đồ 46 check RoboNuggets (dòng `ST5` đổi `SK-02` → `SK-15`) và câu `Official` không có nghĩa MUST; `standards/README.md` thêm bảng «đọc gì khi nào» và mục «Hệ sinh thái» thay `ECOSYSTEM.md`.
  - `MEMO-SKILL-V0.md` và `QA_REPORT.md` chuyển ra ledger OpcOS `archive/` (memo mang `status: superseded`, `superseded_by: standards/SKILL_AUTHORING_STANDARD.md`). `README.md` chỉ sửa link và cây thư mục cho khớp (viết lại gọn ở TK11).
  - Vòng sửa 1: mục «Hệ sinh thái» của `standards/README.md` viết lại theo `system/registry.json` (xưởng chuẩn hoá skill, nhóm `engineering`; bỏ «Nhóm 2 của hệ ACD», số đếm Team / Studio và Bundle E vì registry không có); `DOC_TYPES.md` câu Kết luận khớp mục Skill, file luật được đúng một mục lệnh kiểm trước khi báo xong (bỏ hằng «tối đa 5 lệnh»); `EVALUATION_STANDARD.md` «Phạm vi và nơi lưu» trỏ `evidence/<lô>.json` thay `runs/`.
  - Test: `test_standards_eight_files`, `test_no_thirteen_rules`, `test_harnesses_keeps_checked_lines`, `test_evaluated_block_documented`, `test_doc_types_three_types`, `test_moves_done`, `test_shipped_false_iff_path_outside_skills` (mới); `test_memo_v0_shape` → `test_memo_v0_is_archived_not_in_repo`; `test_authoring_standard_one_form` nâng trần ký tự 5 600 → 7 278 (+30 %); `OLD_NO_FAKE_PASS` bỏ hai file đã xoá, thêm `DOC_TYPES.md` và `HARNESSES.md`. Bộ ca hợp đồng 96/96, không ca lệch.
- **agent-skill-studio:SPR-03 TK2 (chặng 2, skill CSV và `content/` sang `examples/`; chưa phát hành).** **Đổi hợp đồng:** `skills/data-quality-audit/` → `examples/data-quality-audit/` và `content/*` → `examples/`; plugin ship đúng một skill (`skills/skill-creator-studio`), `validate --all` liệt kê 1 skill (trước: 2). Ai gọi `package`/`install`/`validate` với đường `skills/data-quality-audit` phải đổi sang `examples/data-quality-audit`.
  - `evals/catalog.json`: `data-quality-audit` đổi `path` sang `examples/data-quality-audit`, thêm `"shipped": false`, giữ khối `evaluated` SPR-18; `evals/data-quality-audit/` ở lại chỗ cũ (`validate examples/data-quality-audit --require-evals` tìm eval theo tên thư mục skill ở `evals/` của repo).
  - `fmt`: `examples/*.md` là `studio-doc` thay `content/*.md`.
  - CI: bước package chỉ đóng gói `skill-creator-studio`; thêm bước `python studio.py validate examples/data-quality-audit --require-evals`.
  - `examples/eval-cases.md` case 2: «a `!` after the type» → «a `!` right before the colon, after the type or the scope» (Conventional Commits 1.0.0: `feat!:` và `feat(api)!:`).
  - Test: `test_shipped_skills`, `test_catalog_paths` (thay `test_registry_matches_skill_folders`); `test_check_all_puts_type_on_every_report` đếm 1 báo cáo (trước: ≥ 2); `test_the_fixture_is_the_committed_evidence` duyệt mọi file của `tests/fixtures/gate/evals/` so với bản ship. Bộ ca hợp đồng 96/96 không lệch, không đổi `golden.json`.
- **agent-skill-studio:SPR-03 TK1 (chặng 2, cổng đọc bằng chứng gọn; chưa phát hành).** **Đổi hợp đồng:** catalog đánh giá dời `registry/catalog.json` → `evals/catalog.json`; `evals --all` không đọc đường cũ làm dự phòng, thiếu `evals/catalog.json` trong repo có `evals/` là ERROR `EV20` nêu đường mới.
  - Cổng `model_evaluated` thôi đọc `evals/<skill>/runs/<lô>/`; đọc **một file gọn mỗi lô** `evals/<skill>/evidence/<lô>.json` (schema 1: `skill`, `batch`, `source`, `source_sha256`, `logs`, `smoke`, `ab`; khoá lạ, schema khác, kiểu sai, link, placeholder cloud, quá 1 000 000 byte → một dòng `EV20`). Khối `evaluated` thêm khoá bắt buộc `evidence` (đúng `<evals>/evidence/<lô>.json`), `ab_report` nếu có phải bằng nó. Mọi file gọn dưới `evals/*/evidence/` được kiểm `runtime` ∈ `targets`; thư mục `evidence/` không có mục catalog là một dòng lỗi.
  - Engine: `load_batch`, `summarize_logs`, `ran_logs`, `read_logs` (luật đếm vẫn một chỗ; `summarize(runs_dir)` giữ chữ ký). `evals/tools/activation.py` thêm `compact <thư mục thô> --skill S --batch B --out F` (thoát 2 khi `F` đã có) và `compact --verify <thư mục thô> F`; nạp engine từ thư mục của chính repo, đứng đầu `sys.path`, kiểm đúng đường (lệch → thoát 2).
  - Log thô của 6 lô dời ra ledger OpcOS (`system/ledger/agent-skill-studio/evidence/<lô>/<skill>/`); `evals/*/runs/` vào `.gitignore`.
  - Bộ ca hợp đồng: `contract_runner.py --write-golden` bị từ chối khi `golden.json` đã có; dùng `--record-after <id> --by <TK>` (chỉ ghi `after`, không bao giờ ghi `before`); `tests/test_golden_before_frozen.py` canh 96 `before` của `3cc1bd3`. `tests/fixtures/contract/inputs/` đổi sang `evals/catalog.json` + `evals/data-quality-audit/evidence/SPR-18.json`, nên golden không còn tái lập được trên `1211bfa` bằng đúng `inputs/` hiện tại (chấp nhận; 96/96 ca vẫn đạt, không ca nào đổi `after`).
- **agent-skill-studio:SPR-02 (chặng 1b, một nguồn; chưa phát hành).** Engine chỉ còn một bản, ở `skills/skill-creator-studio/scripts/` (`studio.py` là CLI, kèm chín mô-đun `studio_*.py`); `studio.py` ở gốc repo là shim. Bộ ca hợp đồng 96 ca (`tests/fixtures/contract/`, đáp án sinh từ `1211bfa`) khoá đầu ra của CLI. Các thay đổi hợp đồng:
  - **Bỏ** lệnh `sync-template` (thoát 2 như mọi lệnh lạ) và thư mục `templates/skill-template*`: hai khuôn chỉ còn ở `skills/skill-creator-studio/assets/`, lệnh `new` luôn lấy từ đó, trong hay ngoài repo.
  - **Thêm** lệnh `check` (kiểm một skill, thư mục hoặc `SKILL.md`); `validate` và `audit` là bí danh giữ nguyên cờ, mã thoát và JSON; `check <file.md>` từ chối (thoát 2, không đọc) file trong vùng secret/cloud, tên giống secret, placeholder cloud hay luồng NTFS, như `--roots-file`.
  - `evals --all` kiểm thêm `registry/catalog.json` bằng cổng `model_evaluated` đã dời vào engine và báo mã mới `EV20`, thoát 1 khi hỏng; cổng chỉ đọc JSON và tự đếm log trong engine (`summarize` nằm trong `studio_evals`; `evals/tools/activation.py summarize` gọi ngược engine), không nạp hay chạy mã nào của cây ngoài. Repo có `evals/` mà thiếu `registry/catalog.json` là `EV20`; `evaluated.sprint` và `evals` trong catalog phải là đường tương đối thuần dưới gốc repo, sai thì `EV20`. Engine chép rời ra ngoài repo (skill rời, ZIP) hoặc nằm trong cây không có `evals/` bỏ qua cổng.
  - `new --full --lang vi` thoát 0 (trước: thoát 2) và tạo cây full với `SKILL.md` tiếng Việt từ `assets/skill-template-full/SKILL.vi.md`; `SKILL.vi.md` không bao giờ nằm trong skill sinh ra. `new --full` (en) và `new --lang vi` không đổi.
  - Nhận diện gốc repo đổi từ `templates/skill-template/SKILL.md` sang `.claude-plugin/plugin.json` (cùng `standards/SKILL_AUTHORING_STANDARD.md`).
  - Nạp mô-đun: hai engine ở hai chỗ khác nhau trong một tiến trình thì thoát 2 có lời báo thay vì dùng nhầm mô-đun đã nạp; nạp `studio.py` gốc như mô-đun Python không còn được hỗ trợ.
  - `package`/`install`: `SKILL.md` là link, placeholder cloud hoặc nằm trong vùng cloud/secret thì ERROR `PACK` và không đọc (trước: đọc rồi mới chặn). `install --force` khác ổ đĩa mà cây cũ có junction, symlink hoặc placeholder cloud bên trong thì thoát 1 có lời báo, bản cũ giữ nguyên, không chép xuyên link.
  - `fmt` và `skill_dirs` không còn stat đích của symlink/junction: `fmt` báo `skipped (link)` cho mọi symlink (trước: chỉ symlink thư mục hoặc `*.md`); `validate --all` không liệt kê thư mục con của `skills/` là link; `doctor --roots` nhận một gốc là link rồi xét theo đường thật như trước.
  - `doctor --roots <gốc là placeholder cloud>` (thuộc tính cloud, tên không có marker): thoát 0 kèm `skipped: cloud` như `1211bfa`; trong sprint có lúc thoát 2 «root not found» (Tech `RF-T1`, đã sửa) — ghi theo Cổng 2 ĐK-C.
  - `references/NEW_WORKFLOW.md` và `REFINE_WORKFLOW.md` viết lại đúng hình `PR1` (`fmt --check skills/skill-creator-studio` hết cảnh báo).
- **agent-skill-studio:SPR-02, sửa file luật `AGENTS.md:36` (chưa phát hành).** Lý do: lệnh `sync-template` và bản sao khuôn đã bỏ nên câu hướng dẫn cũ sai; đúng một câu đổi thành «Templates live only in `skills/skill-creator-studio/assets/`; edit them there and rerun tests.», không dòng nào khác. Duyệt: Business Reviewer Fable duyệt hộ theo uỷ quyền của Đức ngày 2026-10-27 (CQ1, sửa file luật).
- `registry/catalog.json`: khối `evaluated` nay được phép khi `model_evaluated: false`, thêm `result` (`passed`/`below-threshold`/`partial`/`not_run`, cổng tính lại từ log), `batch_sha` và `batch_sha_kind` (`commit`/`tree`); `data-quality-audit` ghi lô SPR-18 là `below-threshold`. Cờ `true` vẫn đòi đủ ngưỡng như cũ.
- CI chạy ma trận `ubuntu-latest` + `windows-latest` × Python 3.9 + 3.12 (trước: một ô ubuntu, Python 3.11).
- Thêm manifest plugin (`.claude-plugin/`, `.codex-plugin/`) và test đồng bộ version giữa các manifest.
- Thêm log chạy phiên mới cho NEW / AUDIT / REFINE trên Claude Code, Codex và Antigravity (`evals/skill-creator-studio/runs/`): luồng công cụ đạt, skill chưa được kích hoạt tự động và chưa chạy baseline không-skill, nên `model_evaluated` vẫn `false`.
- **agent-skill-studio:SPR-01 TK3 (chưa phát hành):** `package`/`install` thôi duyệt bằng `rglob`; gặp cloud, link, trần duyệt hoặc thư mục tên vùng thì ERROR mã mới `PACK` (không gói thiếu im lặng) và đọc file qua `open_nofollow_read`; cloud nhận thêm qua tag reparse `IO_REPARSE_TAG_CLOUD*` nên báo đúng nhãn cloud; `PINNED` một mình không còn là placeholder; `fmt --fix` tạo `.bak` độc quyền (không ghi xuyên link cài sẵn, lỗi giữa chừng không xoá file cài sẵn) và báo `skipped (link)` cho symlink thư mục trên POSIX.
- **agent-skill-studio:SPR-01 TK4 (chưa phát hành):** `install` thoát 2 khi gốc skill (hoặc thư mục cha dưới HOME/workspace) là symlink/junction, nêu đích thật; cờ mới `--allow-root-link` cho phép có chủ ý. Đích là link sống hoặc dangling → thoát 1 `symlink destination refused` (hết traceback). **Đổi hợp đồng:** bản sao lưu của `--force` chuyển từ `<tên>.backup-<UTC>` cạnh skill sang `<cha gốc skill>/.skill-studio-backups/<tên>-<UTC>/` (ngoài gốc skill); khác ổ đĩa chép rồi xoá. Chép file khi cài qua `open_nofollow_read` + `create_exclusive`.
- **agent-skill-studio:SPR-01 TK6 (chưa phát hành):** `validate`/`doctor` báo đúng. Mã mới `CT11` (WARN, `<!--` không bao giờ đóng). **Đổi hợp đồng:** `SZ1` cho `SKILL.md` quá trần (1 MB ở `doctor`) từ WARN thành ERROR (không đọc được nên không thể đạt), nên `doctor --fail-on error` thoát 1; `new` với tên chứa `claude`/`anthropic` thoát 2 (như `FM5`); `doctor --out` trỏ `.json` không phải báo cáo doctor bị từ chối trước khi quét; `ST8` coi tên thư mục không phân biệt hoa thường; `FM4` và `VI4` báo đúng dòng khoá; rào code thụt sâu trong mục danh sách được nhận; `LINK_RE` nhận đích có một cấp ngoặc đơn (`x(1).md`); `.ads-worktrees` bị loại khỏi quét `doctor`; vùng cloud nhận ra cả qua tên 8.3 trên Windows; `--roots-file` nhận chú thích cuối dòng; `--baseline` khớp theo đường dưới gốc quét thay vì đường tuyệt đối.
- **agent-skill-studio:SPR-01 vòng sửa 1 (chưa phát hành):** **Đổi hành vi:** `package`/`install` dùng cùng luật tên secret với `--export`, không phân biệt hoa thường (`auth.json`, `*.credentials.json`, `.ENV`, `ID_RSA`, `Secrets.JSON`…): gặp thì ERROR `SEC`, thoát 1, không gói/cài (trước đây gói im lặng). `Evals/`, `TESTS/` viết hoa cũng bị loại như `evals/`, `tests/`. `create_exclusive` kiểm `lexists` và so `fstat`/`lstat` (Windows không còn ghi xuyên symlink dangling); `install --force` chỉ chép-rồi-xoá khi lỗi là khác ổ đĩa; `fmt` so định danh trên Windows; `--export` không xoá link dangling có sẵn; chú thích `--roots-file` tuyến tính.
- **SPR-33 (chuẩn viết skill v1), chưa phát hành.** Chỉ thêm, không đổi version:
  - Chuẩn viết skill về một dạng: `standards/SKILL_AUTHORING_STANDARD.md` từ 11 135 xuống 5 599 ký tự, bộ rule `SK-00`…`SK-15` (thêm `SK-14` chữ ép buộc phải có lý do, `SK-15` Contents và điều giữ ở đầu); thêm `standards/MEMO-SKILL-V0.md` (memo v0) và `standards/VIETNAMESE_SKILL_WRITING.md` (chuẩn viết thân tiếng Việt).
  - `validate`: mã kiểm mới `FM5`, `FM6`, `FM8`, `CT10`, `DS4`, `DS5`, `ST2`, `ST3`, `ST5`, `ST7`, `ST8`, `SZ1`, `SZ2` và lint tiếng Việt `VI1`–`VI5`; cờ `--target {portable,claude-code}` (14 khoá riêng Claude Code là `FM6` WARN thay vì lỗi).
  - `new --lang {en,vi}` và `--full`; hai template: `templates/skill-template/` (`SKILL.md`, `SKILL.vi.md`) và `templates/skill-template-full/` (kèm `references/PROCESS_TEMPLATE.md`, `scripts/`, `assets/`, `agents/openai.yaml`); hai skill được tối giản theo template.
  - `install --user` cho Codex (`~/.agents/skills`) và Antigravity (`~/.gemini/config/skills`); Claude Code `--user` thoát 2; thiếu thư mục cha cũng thoát 2.
  - `evals --export agentskills`, `doctor` (quét nhiều gốc skill, chỉ báo cáo) và `fmt` (`--check` mặc định, `--fix` tạo `<file>.bak-<ISO>`, `--no-backup`).
  - Thư mục `content/` (mẫu `description`, case eval, hai skill mẫu tiếng Anh và tiếng Việt), `.gitignore` thêm `.coverage`.
  - **Đổi hợp đồng:** `ST5` (reference >100 dòng thiếu `## Contents`) đổi từ WARN sang ERROR, nên `validate` thoát 1 với skill có reference như vậy; `ST7` (thân `SKILL.md`) vẫn là WARN. `fmt --fix` mặc định chép file đổi sang `<file>.bak-<ISO>` trước khi ghi; `--no-backup` bỏ bản sao đó.
  - Tài liệu trạng thái khớp mã: `README.md`, `QA_REPORT.md`, bốn file `adapters/*` (`Checked: 2026-10-23` kèm nguồn), `registry/SKILL_CATALOG.md`, `templates/README.md`, `standards/README.md`. Lô kích hoạt SPR-33 chạy trên Claude Code; `model_evaluated` vẫn `false`.

## 0.1.0 — 2026-10-12

- Khởi tạo Agent Skill Studio, portable Skill factory và template.
- Quy chuẩn 13 rule được đối chiếu với video, PDF RoboNuggets và official docs.
- Thêm các adapter Claude Code, Codex, Google Antigravity.
- Thêm static validator, audit, scaffold, package, install và kiểm tra eval manifest.
- Evals nằm ngoài runtime Skill; tạo ví dụ kiểm tra data quality và bộ test offline.

**Trạng thái:** prototype usable; static checks + unit tests không thay thế model evaluation thực tế.
