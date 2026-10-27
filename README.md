# Agent Skill Studio

**Bộ tiêu chuẩn và công cụ tạo, audit, cải tiến, kiểm thử và phân phối Agent Skills cho Claude Code, OpenAI Codex và Google Antigravity.**

- Phiên bản: **0.1.0** (thay đổi chưa phát hành: [CHANGELOG.md](CHANGELOG.md); số đo lần kiểm cuối: [QA_REPORT.md](QA_REPORT.md)).
- Ngày đối chiếu nguồn: **2026-10-23** (mỗi adapter ghi nguồn đã mở lại).
- Ngôn ngữ: tài liệu quản trị tiếng Việt; frontmatter của Skill luôn tiếng Anh để dễ di chuyển giữa runtime, thân Skill tiếng Anh hoặc tiếng Việt (`new --lang vi`).
- Thiết kế: **một nguồn quy tắc chung + các adapter riêng + factory Skill + evaluation độc lập**.

> **Quyết định kiến trúc**: `evals/<skill-name>/` đặt **ngoài** `skills/<skill-name>/` để bộ test và đáp án không bị phát hành cùng runtime. Đây là **quy ước của Agent Skill Studio**, không phải yêu cầu bắt buộc của Agent Skills Specification. Có thể dùng colocated evals cho một dự án độc lập, nhưng phải loại chúng khi đóng gói.

## Contents

1. [Repo này giải quyết vấn đề gì?](#repo-này-giải-quyết-vấn-đề-gì)
2. [Cấu trúc](#cấu-trúc)
3. [Khởi động trong 5 phút](#khởi-động-trong-5-phút)
4. [Ba agent và cách cài](#ba-agent-và-cách-cài)
5. [Using from Codex / Antigravity](#using-from-codex--antigravity)
6. [Skill Factory: NEW / AUDIT / REFINE](#skill-factory-new--audit--refine)
7. [Quality gates](#quality-gates)
8. [Phát hành](#phát-hành)
9. [Đọc tài liệu theo nhiệm vụ](#đọc-tài-liệu-theo-nhiệm-vụ)
10. [Nguồn và giới hạn](#nguồn-và-giới-hạn)
11. [ACD Ecosystem Integration](#-acd-ecosystem-integration)

## Repo này giải quyết vấn đề gì?

Nhiều file Markdown không đồng nghĩa một Skill tốt. Khó nhất là thiết kế được:

- **Discovery:** mô tả chính xác *làm gì* và *dùng khi nào* để agent kích hoạt đúng.
- **Execution:** workflow rõ ràng, kiểm tra được, có nhánh xử lý và điều kiện kết thúc.
- **Progressive disclosure:** `SKILL.md` ngắn và chỉ đọc references cần thiết.
- **Portability:** phần chung tuân thủ [Agent Skills Specification](https://agentskills.io/specification), phần riêng nằm trong adapter.
- **Enforcement:** thao tác rủi ro cao bị chặn bằng permission/policy/hook, không phó mặc cho một câu `MUST`.
- **Evidence of improvement:** so sánh một Skill với baseline không Skill và chạy regression sau khi sửa.

**Ranh giới:** repository này tạo và kiểm định **cấu trúc** hoàn toàn offline bằng Python; nó **không thể tự gọi Claude, Codex hay Antigravity** nếu runtime chưa được cài/đăng nhập/cấp quyền. Evals với mô hình cần chạy ở từng agent theo `evals/RUNBOOK.md` rồi ghi bằng chứng.

## Cấu trúc

```text
Agent Skill Studio/
├── README.md                    # Tổng quan, cài đặt, lộ trình
├── CHANGELOG.md                 # Lịch sử thay đổi (chỉ thêm)
├── QA_REPORT.md                 # Số đo lần kiểm cuối
├── LICENSE                      # MIT (chủ sở hữu: Nguyễn Quang Đức)
├── LICENSE_POLICY.md            # Quyết định giấy phép và quy tắc truy vết nguồn
├── ECOSYSTEM.md                 # Khai báo vai trò trong hệ ACD
├── AGENTS.md                    # Chỉ dẫn repo chung cho Codex/Antigravity
├── CLAUDE.md                    # Claude Code: import AGENTS.md và thêm adapter
├── GEMINI.md                    # Antigravity-specific notes, không sao chép rule chung
├── studio.py                    # CLI: new / validate / audit / evals / package / install / sync-template / doctor / fmt
├── .claude-plugin/              # Manifest plugin Claude Code (plugin.json, marketplace.json)
├── .codex-plugin/               # Manifest plugin Codex (plugin.json)
├── standards/
│   ├── README.md                # Chỉ mục chuẩn
│   ├── CORE_STANDARD.md         # Scope, MUST/SHOULD/MAY, thiết kế không phụ thuộc vendor
│   ├── SKILL_AUTHORING_STANDARD.md # 15 quy tắc SK-01..SK-15 + chuẩn manifest SK-00
│   ├── VIETNAMESE_SKILL_WRITING.md # Chuẩn viết thân tiếng Việt + lint VI1-VI5
│   ├── MEMO-SKILL-V0.md         # Memo chuẩn tạm (v0), giữ làm nguồn tham chiếu
│   ├── RULES_AND_PRECEDENCE.md  # Quy tắc nằm ở đâu, tránh conflict/duplication
│   ├── SECURITY_AND_PERMISSIONS.md # Bảo mật supply chain, hành động có side effect
│   ├── EVALUATION_STANDARD.md   # Cách kiểm thử activation, kết quả, regression
│   ├── SKILL_LIFECYCLE.md       # Design -> audit -> ship -> maintain
│   ├── SOURCE_TRACEABILITY.md   # PDF, video, official docs; confidence, caveat
│   └── ROBONUGGETS_46_RULE_MAP.md # Mapping 46 checks community vào chuẩn chung
├── content/                     # Ví dụ để chép và sửa, ngoài skills/ nên không vào gói phát hành
│   ├── README.md
│   ├── descriptions.md          # Bảy cặp description tốt/xấu
│   ├── eval-cases.md            # Ba case eval mẫu
│   ├── exemplar/                # Skill mẫu tiếng Anh
│   └── exemplar-vi/             # Skill mẫu thân tiếng Việt
├── adapters/
│   ├── README.md
│   ├── CLAUDE_CODE_ADAPTER.md
│   ├── CODEX_ADAPTER.md
│   ├── ANTIGRAVITY_ADAPTER.md
│   └── CAPABILITY_MATRIX.md
├── templates/
│   ├── README.md                # Hai template và khi nào dùng
│   ├── project/                 # Mẫu AGENTS.md, CLAUDE.md, GEMINI.md
│   ├── skill-template/          # Mặc định tối giản: SKILL.md (en) và SKILL.vi.md (vi)
│   └── skill-template-full/     # --full: SKILL.md, references/, scripts/, assets/, agents/
├── skills/
│   ├── skill-creator-studio/    # Skill meta-factory: NEW / AUDIT / REFINE
│   │   ├── SKILL.md
│   │   ├── references/
│   │   ├── scripts/studio.py    # CLI có thể chạy cả khi Skill được copy sang repo khác
│   │   └── assets/              # skill-template/ và skill-template-full/: bản phân phối, được CI đồng bộ
│   └── data-quality-audit/     # Skill ví dụ có script xử lý CSV thật
├── evals/                      # KHÔNG được mang vào package Skill
│   ├── RUNBOOK.md
│   ├── tools/                  # activation.py, oracle.py, redact.py
│   ├── skill-creator-studio/
│   │   ├── cases.json
│   │   ├── rubric.md
│   │   ├── expected/, fixtures/, runs/
│   │   └── baselines/BASELINE.md
│   └── data-quality-audit/
│       ├── cases.json
│       ├── rubric.md
│       ├── expected/, fixtures/, runs/
│       └── baselines/BASELINE.md
├── registry/
│   ├── README.md
│   ├── SKILL_CATALOG.md
│   └── catalog.json
├── tests/                      # Unit tests kiểm tra CLI và cấu trúc offline
└── .github/workflows/ci.yml    # Validation + unit tests + packaging smoke test
```

> **Ghi chú cây đích:** cây trên là hiện trạng của repo. Sprint áp dụng kế tiếp (SPEC 9.15 của SPR-33) mới dời: `adapters/*` thành `docs/adapters.md`; xoá `registry/SKILL_CATALOG.md` (giữ `catalog.json`); `QA_REPORT.md`, `ECOSYSTEM.md`, `standards/ROBONUGGETS_46_RULE_MAP.md` vào `docs/`; `templates/project/` thành `templates/starter-project/`; `CLAUDE.md` gốc còn một dòng. Các đường API cứng (`studio.py`, `skills/*`, `standards/SKILL_AUTHORING_STANDARD.md`, `templates/skill-template/SKILL.md`, tên repo) đứng yên. Tới lúc đó, đường dẫn trong tài liệu này vẫn đúng như đã ghi.

### `references/`, `scripts/`, `assets/`, `evals/` khác nhau ra sao?

| Thư mục | Vai trò | Được phân phối cùng Skill? | Ví dụ |
|---|---|---|---|
| `references/` | Đọc để hiểu kiến thức/quy định | Có, theo nhu cầu | DAX rules, JSON schema explanation |
| `scripts/` | Chạy mã deterministic | Có, khi dùng | CSV validator, file converter |
| `assets/` | Sử dụng biểu mẫu/tài nguyên | Có, khi cần | XLSX template, logo, JSON schema |
| `evals/` | Kiểm thử Skill và so sánh baseline | **Mặc định KHÔNG** | prompts, fixtures, rubrics, expected behavior |

Một reference trên 100 dòng nên có Contents. Giữ link trực tiếp từ `SKILL.md` đến các reference thiết yếu. `assets/` có thể chứa file văn bản hay PDF, không chỉ ảnh; phân loại theo **cách dùng** chứ không theo đuôi file.

## Khởi động trong 5 phút

Yêu cầu: **Python 3.9+**, không cần `pip install` cho CLI lõi. Tất cả lệnh chạy tại **repo root**.

```bash
python3 studio.py --help
# xem các skill mẫu và trạng thái
python3 studio.py audit --all
# kiểm tra các skill sản xuất và bộ evals ngoại vi
python3 studio.py validate --all --require-evals
python3 studio.py evals --all
# kiểm thử script và cấu trúc
python3 -m unittest discover -s tests -v
# tạo một skill mới từ mẫu (thân tiếng Anh mặc định; --lang vi cho thân tiếng Việt; --full cho template đầy đủ)
python3 studio.py new powerbi-reporting --output skills --description "Builds and validates Power BI reports. Use when creating Power BI semantic models, DAX measures, or dashboard reports."
# kiểm kiểu trình bày Markdown của vài tài liệu (mặc định chỉ báo cáo, không ghi file)
python3 studio.py fmt --check standards/README.md templates/README.md
# tạo bản package chỉ gồm các file runtime, không kèm evals
python3 studio.py package skills/data-quality-audit --out dist
```

`new` tạo thêm `evals/<name>/cases.json` nếu --output là `skills` ở root repo. Mẫu evals vẫn phải được người viết điền đủ ca kiểm thử thực tế trước production; CLI không tự bịa kết quả model.

Sau khi tạo Skill mới: cập nhật `registry/catalog.json`, thay hướng dẫn mẫu bằng quy trình thực, bổ sung references/assets theo nhu cầu, tạo ít nhất 3 test prompts có positive/negative, kiểm định. `new` chỉ scaffold, **không có nghĩa Skill mới đã đạt chất lượng production**.

**`new`.** `new <name> --description "..."` nhận thêm `--lang {en,vi}` (mặc định `en`; `vi` viết thân tiếng Việt, frontmatter vẫn tiếng Anh), `--full` (template đầy đủ `references/`, `scripts/`, `assets/`, `agents/`, chỉ tiếng Anh; `--full --lang vi` thoát 2) và `--eval-root` (nơi tạo `evals/<name>/`). Hai template còn dấu `STUDIO-DRAFT` nên `package` từ chối đến khi viết thật. Chi tiết: [templates/README.md](templates/README.md); chuẩn viết thân tiếng Việt: [VIETNAMESE_SKILL_WRITING.md](standards/VIETNAMESE_SKILL_WRITING.md).

**`fmt`.** `python3 studio.py fmt --check <đường>` (mặc định) liệt kê lỗi trình bày Markdown (kết thúc dòng, thứ tự khoá, metadata có dấu nháy) và không ghi gì; không bao giờ sửa chữ trong thân. `--fix` áp dụng phần sửa được và trước đó chép từng file đổi sang `<file>.bak-<ISO>` cạnh nó (`.gitignore` đã bỏ qua `*.bak-*`). `--no-backup` bỏ bản sao: trong repo git hãy dùng `--no-backup` vì git đã giữ bản cũ. `--all` quét mọi `*.md` của repo, chỉ báo cáo (không đi cùng `--fix`).

**`evals --export`.** `python3 studio.py evals <skill> --export agentskills --out dist/agentskills` ghi các ca positive thành `<out>/<skill>/evals/evals.json`; `--force` ghi đè file đã xuất; `--out` không được nằm dưới `skills/` hay `evals/`. Lệnh này không gọi model.

```bash
python3 studio.py doctor --roots "<dir1>;<dir2>" --json
```

`python studio.py doctor --roots "<dir1>;<dir2>" --json` — report-only scan of many skill roots; exit 0 clean, 1 findings, 2 cannot scan. Not Claude Code's `/skill-doctor`.

`doctor` is built to read only what is safe. It never lists or opens `~/.secret`, a path that names a cloud folder (`OneDrive`, `SharePoint`), a file or folder that Windows marks as a cloud placeholder, or anything behind a symlink or junction; it refuses a root that is a drive root, your home folder or a folder above it, however it is spelled (through a link, an 8.3 name or a `\\?\` prefix; exit 2, `root too broad`). A synced SharePoint folder whose path has neither word is not recognised by name: add `--skip-marker TEXT` (repeatable, case-insensitive, matched anywhere in the path), for example `--skip-marker "KPIM Joint Stock Company"`. A `SKILL.md` or reference above 1,000,000 bytes is not read, and a skill with more than 5,000 files and folders or more than 12 levels is listed only that far (`SZ1`, listed in `skipped` with reason `limit`). `--roots-file` and `--baseline` are checked before they are opened: not a secret-looking name, not in a cloud or secret zone (also through a link or an 8.3 name), not an NTFS stream (`name:stream`); an error about a root line names its line number, never its text. `--out` may sit in a folder the scan skips (such as `.tmp`), never in a scanned skill or root, never under a name like `.env` or `auth.json`, and it overwrites an existing file only when it is empty or an earlier doctor report (a `.json` file that starts with `{"schema"`); `--out secrets.json` or `.claude.json` is refused (exit 2), as is an NTFS stream.

## Ba agent và cách cài

**Cài như plugin (Claude Code, Codex):** repo có manifest plugin ở `.claude-plugin/` và `.codex-plugin/`. Với Claude Code:

```
/plugin marketplace add ducnguyen221/agent-skill-studio
/plugin install agent-skill-studio@agent-skill-studio
```

Plugin chỉ chứa thư mục `skills/`; `evals/` và `tests/` không nằm trong gói.

**Lệnh install sao chép có kiểm tra, không sửa hoặc ghi đè mục tiêu sẵn có nếu không có `--force`** (`--force` chuyển bản cũ sang `<cha của gốc skill>/.skill-studio-backups/<tên>-<UTC>/`, **ngoài** gốc skill để agent không nạp nhầm, rồi in đường đó; khác ổ đĩa thì chép rồi xoá, lỗi thì skill cũ còn nguyên). Gốc skill (hoặc thư mục cha của nó dưới HOME với `--user`, dưới workspace với `--workspace`) là symlink/junction → thoát 2 và nêu đích thật; cờ `--allow-root-link` cho phép có chủ ý và in đích. Đích `<tên>` là link (kể cả dangling) → thoát 1 `symlink destination refused`, có hay không `--force`: tự gỡ link trước khi cài lại.

```bash
# Thư mục --workspace phải có sẵn (thiếu thì thoát 2)
# Claude Code workspace: .claude/skills/<skill-name>/
python3 studio.py install skills/skill-creator-studio --agent claude --workspace .
# Codex hoặc Google Antigravity: .agents/skills/<skill-name>/
python3 studio.py install skills/skill-creator-studio --agent codex --workspace .
# Nếu đã cài vào .agents/skills, Antigravity có thể dùng cùng bản đó;
# lệnh tiếp theo sẽ từ chối overwrite nếu folder tồn tại.
python3 studio.py install skills/skill-creator-studio --agent antigravity --workspace .
# Cấp người dùng (chỉ codex và antigravity)
python3 studio.py install skills/skill-creator-studio --agent codex --user
python3 studio.py install skills/skill-creator-studio --agent antigravity --user
```

- **Claude Code:** `.claude/skills/<name>`. `--user` **không hỗ trợ** (thoát 2); muốn cài cấp người dùng thì tự chép vào `~/.claude/skills/`. Xem [Claude adapter](adapters/CLAUDE_CODE_ADAPTER.md).
- **Codex:** `.agents/skills/<name>`; `--user` chép vào `~/.agents/skills/<name>`. Xem [Codex adapter](adapters/CODEX_ADAPTER.md).
- **Google Antigravity** (không phải “AntiCraft”): `.agents/skills/<name>`; `--user` chép vào `~/.gemini/config/skills/<name>` (App/IDE). Xem [Antigravity adapter](adapters/ANTIGRAVITY_ADAPTER.md).

`--user` không bao giờ tạo thư mục cha: nếu `~/.agents` hoặc `~/.gemini/config` chưa có thì thoát 2 (`nothing was created`); `--user` đi cùng `--workspace` cũng thoát 2.

**Lưu ý:** cùng một folder `.agents/skills` có thể được cả Codex và Antigravity phát hiện, nhưng invocation UI và chính sách sandbox là khác nhau. Không coi tính năng riêng của Claude (ví dụ `hooks:`) là một phần của chuẩn portable; khoá riêng Claude Code (14 khoá) chỉ qua `validate --target claude-code`.

## Using from Codex / Antigravity

- **Codex.** Cài bằng `install --agent codex --workspace <dự án>` (hoặc `--user`), rồi gọi `$skill-name` hay `/skills`. Danh sách skill nạp ban đầu bị giới hạn (docs: ≤2 % ngữ cảnh hoặc 8 000 ký tự; `[codex 0.147, mã]` 1 024 ký tự mỗi `description` và 8 000 byte thân). Máy kiểm chạy `codex-cli 0.163.0` nên hai con số mã chưa đọc lại ở bản đó. `agents/openai.yaml` là tuỳ chọn, chỉ Codex đọc, có sẵn trong template `--full`. Xem [CODEX_ADAPTER.md](adapters/CODEX_ADAPTER.md).
- **Antigravity.** Cài bằng `install --agent antigravity --workspace <dự án>` (hoặc `--user` cho App/IDE). Tài liệu Antigravity nêu `scripts/`, `examples/`, `resources/`; Studio giữ thêm `references/` và `assets/`, chưa chạy thật để biết agent có đọc không. CLI của Antigravity dùng thư mục toàn cục khác với App/IDE. Xem [ANTIGRAVITY_ADAPTER.md](adapters/ANTIGRAVITY_ADAPTER.md).
- **Giới hạn.** Studio không gọi Codex hay Antigravity; chạy thật theo [evals/RUNBOOK.md](evals/RUNBOOK.md) và ghi log. Chưa có log thì ghi `not_run`. So sánh ba đích: [CAPABILITY_MATRIX.md](adapters/CAPABILITY_MATRIX.md).

## Skill Factory: NEW / AUDIT / REFINE

- **NEW:** lấy yêu cầu -> viết test case & baseline -> chọn mức độ tự do -> scaffold -> hoàn thiện hướng dẫn/scripts/assets -> validate -> chạy eval trên agent -> review -> phát hành.
- **AUDIT:** scan repo hoặc một Skill -> report `ERROR/WARN/INFO` có file/vị trí -> xem bổ sung bằng mắt -> **không tự sửa** -> đề xuất thay đổi theo mức độ ảnh hưởng.
- **REFINE:** xác định bằng chứng thực tế -> đề xuất diff và tác động -> approval -> sửa một nguyên tắc tại một chỗ -> static validate -> chạy lại eval regression.

Hướng dẫn agent sử dụng Skill factory: [skills/skill-creator-studio/SKILL.md](skills/skill-creator-studio/SKILL.md). CLI chạy tại [studio.py](studio.py). `audit` là **static audit**, không thay thế review ngữ nghĩa theo 46 rule.

## Quality gates

1. `SKILL.md` có YAML frontmatter hợp lệ trong **tập con YAML mà CLI offline hỗ trợ** (strings, folded description và metadata string-map); với cú pháp YAML phức tạp phải đơn giản hóa hoặc kiểm tra bổ sung bằng parser YAML đầy đủ bên ngoài CLI. `name`/`description` phải đúng chuẩn.
2. Nội dung vượt 500 dòng được **WARN**, không bị cấm tuyệt đối. Reference Markdown trên 100 dòng thiếu Contents là **ERROR** (`ST5`, `validate` thoát 1); thân `SKILL.md` trên 100 dòng thiếu Contents là **WARN** (`ST7`).
3. Không có local link trỏ ra ngoài Skill, symlink lạ, file `evals/` hoặc secret bị đóng vào package.
4. `evals/<name>/cases.json` hợp lệ, có ít nhất 3 ca và có positive/negative. `studio.py evals` chỉ test **schema**, không chấm được model.
5. Chạy unit tests / CI, test thật với agent mục tiêu theo [evals/RUNBOOK.md](evals/RUNBOOK.md). Định nghĩa: [Không pass giả](standards/EVALUATION_STANDARD.md#không-pass-giả-not_run).
6. Với Skill nguy hiểm, policy gate/permissions độc lập phải chạy thành công; chỉ nhắc trong Markdown **không đủ**.
7. `validate` kiểm cả chuẩn viết (SK-14, SK-15 và các mã như `FM5`, `FM6`, `CT10`, `CT11`, `DS4`, `DS5`, `ST2`, `ST3`, `ST5`, `ST7`, `ST8`, `SZ1`, `SZ2`); thân tiếng Việt còn qua lint `VI1`–`VI5` ([VIETNAMESE_SKILL_WRITING.md](standards/VIETNAMESE_SKILL_WRITING.md)). Đa số là WARN, chỉ lỗi cấu trúc mới chặn.
8. `python3 studio.py fmt --check` và `python3 studio.py doctor` là hai lệnh chỉ báo cáo, chạy được bất cứ lúc nào.

## Xuất fixture (`evals <skill> --export agentskills`): mã `EX*` và rủi ro còn lại

Mọi từ chối in mã `EX*` trên stderr (hoặc trong `--json`). Thoát 2 chỉ với `EX1`; còn lại thoát 1. Lệnh không ghi gì trước khi qua hết các kiểm tra tên; lỗi ghi (`EX8`, `EX13`, `EX6` sau `mkdir`) xoá lại các file lượt này đã tạo (thư mục rỗng có thể còn).

| Mã | Nghĩa | Cách sửa |
|---|---|---|
| `EX1` | Đích xuất nằm dưới `skills/` hoặc dưới `evals/` | Chọn `--out` ngoài hai cây đó |
| `EX2` | Tên skill không phải chữ thường-gạch nối | Dùng tên `a-z0-9-` |
| `EX3` | Eval còn nháp (`status: draft` hoặc chữ `STUDIO-DRAFT`) | Viết ca thật, đặt `status` khác `draft` |
| `EX4` | Fixture bị từ chối: đường không an toàn (`..`, tuyệt đối, có `:`), tên bí mật (`.env*`, `auth.json`, `*.pem`...), nằm trong vùng bí mật/cloud, đi qua symlink/junction, hard link, placeholder cloud, hoặc không đọc được metadata | Bỏ fixture khỏi `cases.json` hoặc thay bằng bản giả không chứa bí mật, nằm trực tiếp trong thư mục eval |
| `EX5` | File đích đã có | Chọn `--out` khác, hoặc thêm `--force` |
| `EX6` | Đích xuất đi qua symlink/junction (kể cả cha bị đổi thành link sau `mkdir`), hoặc đích chính là fixture nguồn | Dùng thư mục `--out` thật, không phải link |
| `EX7` | Hai fixture trùng tên sau xuất (so không phân biệt hoa thường và dạng Unicode) | Đổi tên một trong hai |
| `EX8` | Lỗi ghi (đĩa đầy, quyền...) | Xử lý lỗi hệ thống; chạy lại |
| `EX9` | Tên (bất kỳ thành phần đường) kết thúc bằng dấu chấm hoặc khoảng trắng; Windows bỏ ký tự đó nên `auth.json.` chính là `auth.json` | Bỏ dấu chấm/khoảng trắng cuối |
| `EX10` | Tên thiết bị Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9`, `COM¹`-`COM³`, `LPT¹`-`LPT³`, `CONIN$`, `CONOUT$`, `CLOCK$`; có đuôi hay không, hoa thường đều tính) | Đổi tên file hoặc thư mục |
| `EX11` | Tên ngắn 8.3 (có `~` kèm chữ số, như `AUTH~1.JSO`), có thể che một file bí mật | Dùng tên đầy đủ, không `~` + số |
| `EX12` | Một fixture là file nhưng fixture khác cần nó làm thư mục (`x` và `x/y.csv`) | Đổi tên một trong hai |
| `EX13` | Nguồn bị đổi giữa lúc kiểm và lúc chép (thành link, có thêm tên hard link, hoặc đổi file) | Dừng tiến trình khác đang sửa cây eval, chạy lại |

Tên ghi ra đĩa và trong `evals.json` là dạng Unicode NFC, giữ nguyên hoa thường (`Data.csv` vẫn là `Data.csv`); chỉ phép kiểm trùng `EX7` so không phân biệt hoa thường.

**Rủi ro còn lại.** Trên POSIX nguồn mở bằng `O_NOFOLLOW`. Windows không có cờ đó: nguồn được mở trước, rồi mới so `(st_dev, st_ino)` của handle với `lstat` lúc kiểm và ép `st_nlink == 1`. Hệ quả: (1) việc mở đã đi theo reparse point trước khi so, nên nguồn bị đổi thành link tới placeholder cloud vẫn có thể kích tải trước khi bị từ chối; (2) Ghi độc quyền (`create_exclusive`): POSIX dùng `O_EXCL|O_NOFOLLOW`, bảo vệ thành phần cuối. Windows không có `O_NOFOLLOW` và `CREATE_NEW` đi theo symlink dangling, nên hàm kiểm `os.path.lexists` ngay trước khi mở (tên đã có, kể cả là link, thì từ chối) rồi so `fstat` của handle với `lstat` của đường (lệch, hoặc đường là link, thì đóng handle và báo lỗi, không ghi nội dung); nếu một symlink dangling xuất hiện đúng giữa `lexists` và `open`, một file rỗng vẫn có thể được tạo ở đích của link trước khi bị từ chối. Thư mục cha của đích chỉ được kiểm lại sau `mkdir`, nên kẻ đua cục bộ chạy cùng tài khoản vẫn có một khoảng hở rất hẹp; (3) thư mục cha của **nguồn** (cả POSIX): `export_fixture_check` kiểm link từng thành phần, nhưng `lstat` và `open` sau đó vẫn đi qua các thư mục cha; cha bị đổi thành link giữa kiểm và `lstat` thì so định danh không bắt được (`O_NOFOLLOW` chỉ bảo vệ thành phần cuối), và vòng dọn khi lỗi có thể xoá file cùng tên ở đích mà cha đó trỏ tới; (4) `package` quét secret rồi đọc lại khi nén, nội dung bị ghi giữa hai lần có thể khác bản đã quét. Công cụ bảo vệ khỏi tệp sai và nhầm lẫn, không phải khỏi một tiến trình thù địch cùng quyền; đừng xuất từ cây eval mà tiến trình khác đang ghi.

## Đóng gói (`package`, `install`): mã `PACK`

`package` và `install` duyệt cây skill bằng bộ duyệt có kiểm link và cloud (không dùng `rglob`), vẫn bỏ `evals/`, `tests/`, `.git`, cache. Mọi lỗi dưới đây là ERROR mã `PACK`, thoát 1, không ghi gói:

| Mã | Nghĩa | Cách sửa |
|---|---|---|
| `PACK` | Gặp symlink/junction, placeholder cloud (cờ cloud hoặc tag `IO_REPARSE_TAG_CLOUD*`), thư mục tên vùng (thư mục bí mật, `OneDrive`, `SharePoint`), cây vượt trần duyệt (5 000 mục / 12 tầng), file có hơn một tên (hard link) hoặc bị đổi giữa lúc kiểm và lúc đọc, file trên 25 MB, bản nháp `STUDIO-DRAFT` | Bỏ link/thư mục đó khỏi skill, tải file cloud thủ công, thu gọn cây, rồi chạy lại |

Tên file giống secret (cùng luật với `--export`, không phân biệt hoa thường: `.env*`, `auth.json`, `*.credentials.json`, `credentials.json`, `secrets.json`, `id_rsa`, `id_ed25519`, `*.pem`, `*.key`, `*.p12`, `*.pfx`) là ERROR mã `SEC` ở `package` và `install`: thoát 1, không gói, không cài; dòng «Excluded» chỉ liệt kê `evals/`, `tests/` và thư mục cache (cũng không phân biệt hoa thường: `Evals/`, `TESTS/`). `install --force` chỉ chép-rồi-xoá bản cũ khi sao lưu sang ổ khác; mọi lỗi đổi tên khác dừng ngay với skill cũ còn nguyên, và nếu bản sao lưu đã đủ nhưng bản cũ không xoá hết thì lời báo nêu đường sao lưu. `fmt` so định danh (`lstat` lúc đọc) trên cả Windows.

Không bao giờ đọc nội dung placeholder cloud. `PINNED` một mình (file đã tải sẵn) không còn bị coi là placeholder; `PINNED` kèm `RECALL_ON_DATA_ACCESS`, `RECALL_ON_OPEN`, `OFFLINE` hay `UNPINNED` vẫn là cloud. `validate`/`doctor` giữ `SZ2` ở mức WARN.

## Phát hành

Trước khi phát hành: `python3 studio.py doctor`, rồi `fmt --check` trên danh sách file của đợt (13 đường của SPR-33, phải thoát 0 và báo `0 skipped`):

```bash
python3 studio.py fmt --check standards/MEMO-SKILL-V0.md standards/SKILL_AUTHORING_STANDARD.md standards/SOURCE_TRACEABILITY.md standards/EVALUATION_STANDARD.md standards/CORE_STANDARD.md standards/README.md standards/VIETNAMESE_SKILL_WRITING.md content templates/skill-template templates/skill-template-full templates/README.md
```

`fmt --check` không kèm đường thì thoát 2; `fmt --check --all` hiện thoát 1 vì còn dòng cũ và file chuẩn không được chạm trong đợt này. Sau đó `validate --all --require-evals`, `evals --all`, `sync-template --check` và `python3 -m unittest discover -s tests`. Ghi số đo vào [QA_REPORT.md](QA_REPORT.md), thêm mục vào [CHANGELOG.md](CHANGELOG.md) (chỉ thêm, không ghi đè), rồi mới tăng version. `model_evaluated` giữ `false` cho đến khi `registry/catalog.json` có đủ bằng chứng đếm lại được.

## Đọc tài liệu theo nhiệm vụ

| Nhu cầu | Đọc tài liệu |
|---|---|
| Học cách thiết kế Skill | [SKILL_AUTHORING_STANDARD.md](standards/SKILL_AUTHORING_STANDARD.md) |
| Biết vì sao phải làm một rule | [SOURCE_TRACEABILITY.md](standards/SOURCE_TRACEABILITY.md) |
| Kiểm tra 46 rule community | [ROBONUGGETS_46_RULE_MAP.md](standards/ROBONUGGETS_46_RULE_MAP.md) |
| Triển khai cùng Claude/Codex/AGY | [adapters/](adapters/CAPABILITY_MATRIX.md) |
| Viết thân Skill bằng tiếng Việt | [VIETNAMESE_SKILL_WRITING.md](standards/VIETNAMESE_SKILL_WRITING.md), skill mẫu trong [content/](content/README.md) |
| Chép mẫu `description`, case eval, skill mẫu | [content/README.md](content/README.md) |
| Chọn template khi tạo Skill | [templates/README.md](templates/README.md) |
| Viết test/baseline | [EVALUATION_STANDARD.md](standards/EVALUATION_STANDARD.md), [evals/RUNBOOK.md](evals/RUNBOOK.md) |
| Kiểm soát permission hoặc hooks | [SECURITY_AND_PERMISSIONS.md](standards/SECURITY_AND_PERMISSIONS.md) |
| Muốn tạo Skill mới | `python3 studio.py new ...`, sau đó dùng [Skill factory](skills/skill-creator-studio/SKILL.md) |

## Nguồn và giới hạn

Tham khảo trực tiếp: [Agent Skills Specification](https://agentskills.io/specification), [Claude Skills](https://code.claude.com/docs/en/skills), [Anthropic Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices), [OpenAI Build Skills](https://learn.chatgpt.com/docs/build-skills), [Google Antigravity Skills](https://www.antigravity.google/docs/skills), [robonuggets/skill-creator-plus](https://github.com/robonuggets/skill-creator-plus), video [VQyYzLJ6xos](https://www.youtube.com/watch?v=VQyYzLJ6xos) và PDF người dùng cung cấp *The 10 SKILL Rules* (trang 3–10). Xem [source traceability](standards/SOURCE_TRACEABILITY.md) trước khi diễn đạt bất kỳ đề xuất nội bộ nào như một chuẩn chính thức.

Giấy phép: **MIT** ([LICENSE](LICENSE), quyết định 12/10/2026, xem [LICENSE_POLICY.md](LICENSE_POLICY.md)). Repo này **không sao chép mã nguồn của RoboNuggets**; các scripts ở đây được tự triển khai theo tiêu chí kiểm tra công khai. Nội dung public có thể thay đổi sau 12/10/2026; kiểm tra lại trước khi nâng bản lớn. Bản phân phối này không tự gọi agent. Lô kích hoạt đã ghi (SPR-18, SPR-33) chạy trên Claude Code, SPR-18 thêm Codex; Antigravity `not_run`; `model_evaluated` giữ `false`. Số đo và giới hạn: [QA_REPORT.md](QA_REPORT.md).

## 🤝 ACD Ecosystem Integration

Repo là Studio nhóm 2 — xưởng nền (Skill Factory) trong hệ thống nhiều repo ACD, nhận `production-brief.md` có khối Skill Spec và trả báo cáo AUDIT, diff cùng kết quả validate/eval cho repo sở hữu skill. Khai báo đủ 5 dòng (Role, Upstream, Downstream, Bundles, Handoff) tại [ECOSYSTEM.md](ECOSYSTEM.md).

## Author

**Nguyễn Quang Đức** (Tobi) — founder and CEO of KPIM and co-founder of COMPA Class; Data/AI practitioner and instructor in Vietnam.

Website: https://ducnguyen.vn · GitHub: [@ducnguyen221](https://github.com/ducnguyen221) · Contact: ducnguyen.ams@gmail.com
