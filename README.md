# Agent Skill Studio

**Bộ chuẩn và công cụ để tạo, kiểm, cải tiến, đo và phân phối Agent Skills cho Claude Code, OpenAI Codex và Google Antigravity.**

> **Kết luận:** repo có hai skill phát hành (`skills/skill-creator-studio` viết và sửa từng skill, `skills/skill-curator` nhìn cả thư viện skill), một engine Python không cần cài thêm gì, tám file chuẩn và một cổng
> đếm lại bằng chứng đánh giá. Phiên bản **0.4.0**; thay đổi từng bản ở [CHANGELOG.md](CHANGELOG.md). Chạy `python3 studio.py --help` là thấy hết lệnh.

## Repo làm gì

Nhiều file Markdown chưa làm nên một Skill tốt. Studio giữ sáu việc:

- **Mô tả đúng:** `description` nói rõ làm gì và dùng khi nào, để agent kích hoạt đúng lúc.
- **Quy trình kiểm được:** các bước có nhánh lỗi và điều kiện kết thúc; `check` bắt chỗ thiếu mà không gọi model.
- **Nạp từng phần:** `SKILL.md` ngắn, phần chi tiết nằm ở `references/` và chỉ đọc khi cần.
- **Mang đi được:** phần chung theo [Agent Skills Specification](https://agentskills.io/specification); phần riêng từng agent ở [HARNESSES.md](standards/HARNESSES.md).
- **Chặn bằng máy:** việc rủi ro bị chặn bằng quyền, chính sách hoặc hook, không phó mặc cho một chữ `MUST`.
- **Có bằng chứng:** so Skill với lượt không Skill, rồi chạy lại hồi quy sau mỗi lần sửa.

**Ranh giới:** engine kiểm cấu trúc hoàn toàn ngoại tuyến và **không gọi** Claude, Codex hay Antigravity. Đo bằng model thật chạy theo [evals/RUNBOOK.md](evals/RUNBOOK.md); chưa chạy thì ghi `not_run`, không ghi đạt giả ([Không pass giả](standards/EVALUATION_STANDARD.md#không-pass-giả-not_run)).

## Cây thư mục: sáu thư mục thư viện và `docs/`

```text
agent-skill-studio/
├── README.md, CHANGELOG.md, LICENSE, LICENSE_POLICY.md
├── AGENTS.md, CLAUDE.md, GEMINI.md   # luật của repo cho ba agent (CLAUDE.md nạp AGENTS.md)
├── studio.py                         # vỏ mỏng gọi engine trong skill
├── .claude-plugin/, .codex-plugin/   # manifest plugin; .github/workflows/ci.yml
├── standards/   # 8 file chuẩn, bắt đầu từ README.md và SKILL_AUTHORING_STANDARD.md
├── skills/      # skill phát hành: skill-creator-studio, skill-curator (SKILL.md, references/, scripts/, assets/)
├── templates/   # starter-project/ (mẫu luật cho dự án khác); hai khuôn skill nằm ở skills/…/assets/
├── examples/    # mẫu để chép: descriptions.md, eval-cases.md, exemplar/, exemplar-vi/, data-quality-audit/
├── evals/       # catalog.json, RUNBOOK.md, tools/, <skill>/{cases.json, rubric.md, expected/, fixtures/, evidence/}
├── tests/       # unittest ngoại tuyến, bộ ca hợp đồng của CLI trong fixtures/contract/
└── docs/        # website tĩnh trên OpcOS Design System (xem docs/README.md); không vào gói phát hành
```

Mã dùng chung và CLI nằm ở `skills/skill-creator-studio/scripts/` (`studio.py` cùng các mô-đun `studio_*.py`); mã `catalog` nằm ở `skills/skill-curator/scripts/`. `evals/` và `tests/` không vào gói phát hành. Log thô của lượt đo nằm ở sổ OpcOS; repo chỉ giữ file gọn `evals/<skill>/evidence/<lô>.json` mà cổng đếm lại được.

## Khởi động trong 5 phút

Cần **Python 3.9+**, không cần `pip install`. Mọi lệnh chạy tại gốc repo.

```bash
python3 studio.py check skills/skill-creator-studio        # kiểm một skill
python3 studio.py validate --all --require-evals           # kiểm mọi skill và bộ evals
python3 studio.py evals --all                              # schema eval và cổng model_evaluated
python3 studio.py fmt --check --all                        # kiểu trình bày Markdown, không ghi file
python3 -m unittest discover -s tests                      # toàn bộ test ngoại tuyến
python3 studio.py new my-skill --output skills --description "Does X. Use when Y."
```

`new` chỉ dựng khung và để dấu `STUDIO-DRAFT`; `package` từ chối đến khi bạn viết thật. Sau `new`: thêm mục vào `evals/catalog.json`, viết ít nhất 3 ca (có ca dương và ca âm), rồi `check`. Chi tiết khuôn: [templates/README.md](templates/README.md).

## Ba agent và cách cài

Cài như plugin (Claude Code, Codex): manifest ở `.claude-plugin/` và `.codex-plugin/`, gói chỉ chứa `skills/`.

```text
# Claude Code (trong phiên, hoặc CLI: claude plugin marketplace add … / claude plugin install …)
/plugin marketplace add ducnguyen221/agent-skill-studio
/plugin install agent-skill-studio@agent-skill-studio
# Codex CLI
codex plugin marketplace add ducnguyen221/agent-skill-studio
codex plugin add agent-skill-studio@agent-skill-studio
# Nâng cấp: claude plugin marketplace update agent-skill-studio && claude plugin update agent-skill-studio@agent-skill-studio
#           codex plugin marketplace upgrade agent-skill-studio && codex plugin add agent-skill-studio@agent-skill-studio
# Gỡ:       claude plugin uninstall agent-skill-studio@agent-skill-studio · codex plugin remove agent-skill-studio@agent-skill-studio
```

Cài riêng một skill bằng `install` (sao chép có kiểm tra, không ghi đè nếu thiếu `--force`):

```bash
python3 studio.py install skills/skill-creator-studio --agent claude --workspace .
python3 studio.py install skills/skill-creator-studio --agent codex --workspace .        # .agents/skills/
python3 studio.py install skills/skill-creator-studio --agent antigravity --user         # ~/.gemini/config/skills/
python3 studio.py install skills/skill-curator --agent codex --workspace .               # skill thứ hai, cùng cách
```

- **Claude Code:** `.claude/skills/<tên>`; `--user` không hỗ trợ (thoát 2), tự chép vào `~/.claude/skills/`.
- **Codex:** `.agents/skills/<tên>`; `--user` chép vào `~/.agents/skills/`. Gọi bằng `$tên-skill` hoặc `/skills`.
- **Antigravity:** `.agents/skills/<tên>`; `--user` chép vào `~/.gemini/config/skills/`. Chưa chạy thật nên chưa biết agent có đọc `references/` hay không.
- Gốc skill là symlink hoặc junction thì `install` thoát 2 (cờ `--allow-root-link` cho phép có chủ ý); đích là link thì thoát 1. `--force` đưa bản cũ sang `.skill-studio-backups/` ngoài gốc skill.

Đường cài, giới hạn và cách nạp luật của từng agent: [HARNESSES.md](standards/HARNESSES.md).

## Lệnh

| Lệnh | Việc | Ghi chú |
|---|---|---|
| `new` | dựng skill mới và bộ eval rỗng | `--lang vi` thân tiếng Việt, `--full` khuôn đầy đủ; không ghi đè file eval đã có |
| `check` | kiểm tĩnh một skill, hoặc một file workflow hay file luật có `type:` | chỉ đọc, không sửa file |
| `validate`, `audit` | bí danh của `check` | giữ nguyên cờ, mã thoát và JSON |
| `evals` | kiểm schema eval; `--all` thêm cổng `model_evaluated` | `--export agentskills` xuất ca dương, không gọi model |
| `package` | đóng gói ZIP chỉ gồm file chạy | bỏ `evals/`, `tests/`; gặp tên giống secret thì dừng |
| `install` | chép skill vào thư mục khám phá của agent | xem mục trên |
| `doctor` | quét nhiều gốc skill, chỉ báo cáo | không mở vùng secret, cloud hay link; `--roots-from opcos`, `--by-pack`, `--docs`; thoát 0, 1 hoặc 2 |
| `catalog` | bảng một dòng mỗi skill nguồn; `--overlap` gắn nhãn cặp trùng, `--installed` so bản đã cài | chỉ đọc; `--roots-from opcos`, `--json`/`--out`, `--md` (skill `skill-curator`) |
| `fmt` | kiểm hoặc sửa kiểu trình bày Markdown | `--fix` chép bản `.bak-<ISO>` trước (bỏ bằng `--no-backup`); `--all` quét cả repo, bỏ qua fixture |

## Mã của engine

Mỗi từ chối in một mã trên stderr (và trong `--json`). Các mã người dùng hay gặp:

| Mã | Khi nào | Cách sửa |
|---|---|---|
| `INPUT` | `SKILL.md` nằm trong vùng cloud hoặc secret, là placeholder cloud, hoặc là symlink hay junction | đưa skill ra khỏi vùng đó, hoặc thay link bằng file thật |
| `EV20` | catalog hỏng hoặc lệch bằng chứng; thiếu `evals/catalog.json` hay file gọn mà khối `evaluated` trỏ tới; thư mục `evidence/` có link | sửa catalog, bổ sung bằng chứng, bỏ link |
| `PACK` | `package`/`install` gặp link, placeholder cloud, thư mục vùng cấm, cây quá 5 000 mục hoặc 12 tầng, hard link, file trên 25 MB | bỏ phần đó khỏi skill rồi chạy lại |
| `SEC` | tên file giống secret (`.env*`, `auth.json`, `*.pem`, `*.key`…), không phân biệt hoa thường | đổi tên hoặc bỏ file |
| `EX1`–`EX13` | `evals <skill> --export agentskills` từ chối: đích dưới `skills/` hay `evals/` (thoát 2), tên sai, eval còn nháp, fixture không an toàn, đích đã có, đích qua link, tên trùng, lỗi ghi | đọc dòng lỗi, đổi `--out` hoặc fixture |

**`INPUT`.** Với đầu vào là thư mục, engine quyết định về `SKILL.md` trước khi mở nó; bị từ chối thì thoát 1, không đọc và không in `name`. Đầu vào là file thì bị từ chối bằng `ERROR:` ở stderr, thoát 2. File `SKILL.md` có hơn một tên (hard link) cũng bị từ chối (`INPUT`).

**`EV20`.** Khi engine nằm trong repo (tính từ chính file engine, không theo thư mục đang đứng), `evals --all` đối chiếu `model_evaluated`, `status` và khối `evaluated` của `evals/catalog.json` với số đếm lại từ `evals/<skill>/evidence/<lô>.json`. File gọn sinh bằng `evals/tools/activation.py compact`, kiểm lại bằng `compact --verify`. Engine chép rời ra ngoài repo bỏ qua cổng. Mỗi vấn đề là một ERROR, thoát 1.

Rủi ro còn lại: Studio không đi theo link ở bất kỳ cấp nào **dưới** gốc neo (gốc quét, thư mục hiện hành, hoặc thư mục chứa file đầu ra). Link **tại hoặc phía trên** gốc neo — ví dụ `/tmp` của macOS hay thư mục đổi chủ của OneDrive — được nhận có chủ ý. Trên Windows Studio dùng `_winapi.CreateFile` (module riêng của CPython); bản Python thiếu nó thì Studio từ chối mở thay vì đọc thường. File OneDrive (kể cả đã tải) mang reparse point nên bị coi như link và bị từ chối. File đầu vào (`--roots-file`, `--baseline`) nằm ngoài thư mục hiện hành chỉ được bảo vệ ở tên cuối: thư mục chứa nó được theo link. Đừng xuất từ cây eval mà tiến trình khác đang ghi. Trên macOS, `/tmp` và `/var` (link hệ thống tới `/private/…`) được phép làm đích của `new --output`; link do người dùng tạo vẫn bị từ chối (hỏng-đóng, kể cả khi có `--eval-root`).

## Đọc gì khi nào

Bảng đầy đủ nằm ở [standards/README.md](standards/README.md). Lối tắt:

| Khi bạn… | Đọc |
|---|---|
| học cách thiết kế một Skill, hiểu luật `SK-00`…`SK-15` | [SKILL_AUTHORING_STANDARD.md](standards/SKILL_AUTHORING_STANDARD.md) |
| viết thân Skill bằng tiếng Việt | [VIETNAMESE_SKILL_WRITING.md](standards/VIETNAMESE_SKILL_WRITING.md), mẫu ở [examples/](examples/README.md) |
| soạn skill, workflow hay file luật agent | [DOC_TYPES.md](standards/DOC_TYPES.md) |
| triển khai trên Claude, Codex hoặc Antigravity | [HARNESSES.md](standards/HARNESSES.md) |
| viết test, đo bằng model, ghi `not_run` | [EVALUATION_STANDARD.md](standards/EVALUATION_STANDARD.md), [evals/RUNBOOK.md](evals/RUNBOOK.md) |
| xử lý quyền, hook, secret | [SECURITY_AND_PERMISSIONS.md](standards/SECURITY_AND_PERMISSIONS.md) |
| tra nguồn của một luật | [SOURCE_TRACEABILITY.md](standards/SOURCE_TRACEABILITY.md) |
| cần ví dụ hoặc khuôn để chép | [examples/README.md](examples/README.md), [templates/README.md](templates/README.md) |

## Phát hành

Trước khi phát hành: `python3 studio.py doctor`, rồi `fmt --check --all`, `validate --all --require-evals`, `evals --all` và `python3 -m unittest discover -s tests` đều phải thoát 0. Ghi thay đổi vào [CHANGELOG.md](CHANGELOG.md) (chỉ thêm, không ghi đè) rồi mới tăng phiên bản ở `VERSION` của engine và ba manifest. `model_evaluated` giữ `false` cho đến khi `evals/catalog.json` có bằng chứng đủ ngưỡng đếm lại được. Giấy phép **MIT** ([LICENSE](LICENSE), [LICENSE_POLICY.md](LICENSE_POLICY.md)); repo không sao chép mã của RoboNuggets.

## Tác giả

**Nguyễn Quang Đức** (Tobi): sáng lập và CEO KPIM, đồng sáng lập COMPA Class; làm và giảng dạy Data/AI tại Việt Nam.

Trang web: https://ducnguyen.vn · GitHub: [@ducnguyen221](https://github.com/ducnguyen221) · Liên hệ: ducnguyen.ams@gmail.com
