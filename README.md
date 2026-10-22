# Agent Skill Studio

**Bộ tiêu chuẩn và công cụ tạo, audit, cải tiến, kiểm thử và phân phối Agent Skills cho Claude Code, OpenAI Codex và Google Antigravity.**

- Phiên bản: **0.1.0** (starter repository có kiểm thử cấu trúc thực tế).
- Ngày đối chiếu nguồn: **2026-10-12**.
- Ngôn ngữ: tài liệu quản trị tiếng Việt; instruction trong Skill dùng tiếng Anh để dễ di chuyển giữa runtime.
- Thiết kế: **một nguồn quy tắc chung + các adapter riêng + factory Skill + evaluation độc lập**.

> **Quyết định kiến trúc**: `evals/<skill-name>/` đặt **ngoài** `skills/<skill-name>/` để bộ test và đáp án không bị phát hành cùng runtime. Đây là **quy ước của Agent Skill Studio**, không phải yêu cầu bắt buộc của Agent Skills Specification. Có thể dùng colocated evals cho một dự án độc lập, nhưng phải loại chúng khi đóng gói.

## Contents

1. [Repo này giải quyết vấn đề gì?](#repo-này-giải-quyết-vấn-đề-gì)
2. [Cấu trúc](#cấu-trúc)
3. [Khởi động trong 5 phút](#khởi-động-trong-5-phút)
4. [Ba agent và cách cài](#ba-agent-và-cách-cài)
5. [Skill Factory: NEW / AUDIT / REFINE](#skill-factory-new--audit--refine)
6. [Quality gates](#quality-gates)
7. [Đọc tài liệu theo nhiệm vụ](#đọc-tài-liệu-theo-nhiệm-vụ)
8. [Nguồn và giới hạn](#nguồn-và-giới-hạn)
9. [ACD Ecosystem Integration](#-acd-ecosystem-integration)

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
├── LICENSE                      # MIT (chủ sở hữu: Nguyễn Quang Đức)
├── LICENSE_POLICY.md            # Quyết định giấy phép và quy tắc truy vết nguồn
├── AGENTS.md                    # Chỉ dẫn repo chung cho Codex/Antigravity
├── CLAUDE.md                    # Claude Code: import AGENTS.md và thêm adapter
├── GEMINI.md                    # Antigravity-specific notes, không sao chép rule chung
├── studio.py                    # CLI chung: new / validate / audit / evals / package / install
├── standards/
│   ├── CORE_STANDARD.md         # Scope, MUST/SHOULD/MAY, thiết kế không phụ thuộc vendor
│   ├── SKILL_AUTHORING_STANDARD.md # 13 quy tắc SK-01..SK-13 + chuẩn manifest SK-00
│   ├── RULES_AND_PRECEDENCE.md  # Quy tắc nằm ở đâu, tránh conflict/duplication
│   ├── SECURITY_AND_PERMISSIONS.md # Bảo mật supply chain, hành động có side effect
│   ├── EVALUATION_STANDARD.md   # Cách kiểm thử activation, kết quả, regression
│   ├── SKILL_LIFECYCLE.md       # Design -> audit -> ship -> maintain
│   ├── SOURCE_TRACEABILITY.md   # PDF, video, official docs; confidence, caveat
│   └── ROBONUGGETS_46_RULE_MAP.md # Mapping 46 checks community vào chuẩn chung
├── adapters/
│   ├── CLAUDE_CODE_ADAPTER.md
│   ├── CODEX_ADAPTER.md
│   ├── ANTIGRAVITY_ADAPTER.md
│   └── CAPABILITY_MATRIX.md
├── templates/
│   ├── project/                 # Mẫu AGENTS.md, CLAUDE.md, GEMINI.md
│   └── skill-template/          # Mẫu skill: SKILL.md, references/, scripts/, assets/
├── skills/
│   ├── skill-creator-studio/    # Skill meta-factory: NEW / AUDIT / REFINE
│   │   ├── SKILL.md
│   │   ├── references/
│   │   ├── scripts/studio.py    # CLI có thể chạy cả khi Skill được copy sang repo khác
│   │   └── assets/skill-template/ # Bản template phân phối, được CI đồng bộ
│   └── data-quality-audit/     # Skill ví dụ có script xử lý CSV thật
├── evals/                      # KHÔNG được mang vào package Skill
│   ├── RUNBOOK.md
│   ├── skill-creator-studio/
│   │   ├── cases.json
│   │   ├── rubric.md
│   │   └── baselines/BASELINE.md
│   └── data-quality-audit/
│       ├── cases.json
│       ├── rubric.md
│       ├── fixtures/
│       └── baselines/BASELINE.md
├── registry/
│   ├── SKILL_CATALOG.md
│   └── catalog.json
├── tests/                      # Unit tests kiểm tra CLI và cấu trúc offline
└── .github/workflows/ci.yml    # Validation + unit tests + packaging smoke test
```

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
# tạo một skill mới từ mẫu, dùng alias duy nhất
python3 studio.py new powerbi-reporting --output skills --description "Builds and validates Power BI reports. Use when creating Power BI semantic models, DAX measures, or dashboard reports." 
# tạo bản package chỉ gồm các file runtime, không kèm evals
python3 studio.py package skills/data-quality-audit --out dist
```

`new` tạo thêm `evals/<name>/cases.json` nếu --output là `skills` ở root repo. Mẫu evals vẫn phải được người viết điền đủ ca kiểm thử thực tế trước production; CLI không tự bịa kết quả model.

Sau khi tạo Skill mới: cập nhật `registry/catalog.json`, thay hướng dẫn mẫu bằng quy trình thực, bổ sung references/assets theo nhu cầu, tạo ít nhất 3 test prompts có positive/negative, kiểm định. `new` chỉ scaffold, **không có nghĩa Skill mới đã đạt chất lượng production**.

## Ba agent và cách cài

**Cài như plugin (Claude Code, Codex):** repo có manifest plugin ở `.claude-plugin/` và `.codex-plugin/`. Với Claude Code:

```
/plugin marketplace add ducnguyen221/agent-skill-studio
/plugin install agent-skill-studio@agent-skill-studio
```

Plugin chỉ chứa thư mục `skills/`; `evals/` và `tests/` không nằm trong gói.

**Lệnh install sao chép có kiểm tra, không sửa hoặc ghi đè mục tiêu sẵn có nếu không có `--force`.**

```bash
# Claude Code workspace: .claude/skills/<skill-name>/
python3 studio.py install skills/skill-creator-studio --agent claude --workspace .
# Codex hoặc Google Antigravity: .agents/skills/<skill-name>/
python3 studio.py install skills/skill-creator-studio --agent codex --workspace .
# Nếu đã cài vào .agents/skills, Antigravity có thể dùng cùng bản đó;
# lệnh tiếp theo sẽ từ chối overwrite nếu folder tồn tại.
python3 studio.py install skills/skill-creator-studio --agent antigravity --workspace .
```

- **Claude Code:** `.claude/skills/<name>` (user scope `~/.claude/skills/`). Xem [Claude adapter](adapters/CLAUDE_CODE_ADAPTER.md).
- **Codex:** `.agents/skills/<name>` (user scope `~/.agents/skills/`). Xem [Codex adapter](adapters/CODEX_ADAPTER.md).
- **Google Antigravity** (không phải “AntiCraft”): `.agents/skills/<name>`, user `~/.gemini/config/skills/<name>` theo docs. Xem [Antigravity adapter](adapters/ANTIGRAVITY_ADAPTER.md).

**Lưu ý:** cùng một folder `.agents/skills` có thể được cả Codex và Antigravity phát hiện, nhưng invocation UI và chính sách sandbox là khác nhau. Không coi tính năng riêng của Claude (ví dụ `hooks:`) là một phần của chuẩn portable. Script `install` hiện chỉ hỗ trợ project/workspace scope để tránh thay đổi cấu hình toàn máy.

## Skill Factory: NEW / AUDIT / REFINE

- **NEW:** lấy yêu cầu -> viết test case & baseline -> chọn mức độ tự do -> scaffold -> hoàn thiện hướng dẫn/scripts/assets -> validate -> chạy eval trên agent -> review -> phát hành.
- **AUDIT:** scan repo hoặc một Skill -> report `ERROR/WARN/INFO` có file/vị trí -> xem bổ sung bằng mắt -> **không tự sửa** -> đề xuất thay đổi theo mức độ ảnh hưởng.
- **REFINE:** xác định bằng chứng thực tế -> đề xuất diff và tác động -> approval -> sửa một nguyên tắc tại một chỗ -> static validate -> chạy lại eval regression.

Hướng dẫn agent sử dụng Skill factory: [skills/skill-creator-studio/SKILL.md](skills/skill-creator-studio/SKILL.md). CLI chạy tại [studio.py](studio.py). `audit` là **static audit**, không thay thế review ngữ nghĩa theo 46 rule.

## Quality gates

1. `SKILL.md` có YAML frontmatter hợp lệ trong **tập con YAML mà CLI offline hỗ trợ** (strings, folded description và metadata string-map); với cú pháp YAML phức tạp phải đơn giản hóa hoặc kiểm tra bổ sung bằng parser YAML đầy đủ bên ngoài CLI. `name`/`description` phải đúng chuẩn.
2. Nội dung vượt 500 dòng được **WARN**, không bị cấm tuyệt đối. Reference Markdown trên 100 dòng thiếu Contents được **WARN**.
3. Không có local link trỏ ra ngoài Skill, symlink lạ, file `evals/` hoặc secret bị đóng vào package.
4. `evals/<name>/cases.json` hợp lệ, có ít nhất 3 ca và có positive/negative. `studio.py evals` chỉ test **schema**, không chấm được model.
5. Chạy unit tests / CI, test thật với agent mục tiêu theo [evals/RUNBOOK.md](evals/RUNBOOK.md). Định nghĩa: [Không pass giả](standards/EVALUATION_STANDARD.md#không-pass-giả-not_run).
6. Với Skill nguy hiểm, policy gate/permissions độc lập phải chạy thành công; chỉ nhắc trong Markdown **không đủ**.

## Đọc tài liệu theo nhiệm vụ

| Nhu cầu | Đọc tài liệu |
|---|---|
| Học cách thiết kế Skill | [SKILL_AUTHORING_STANDARD.md](standards/SKILL_AUTHORING_STANDARD.md) |
| Biết vì sao phải làm một rule | [SOURCE_TRACEABILITY.md](standards/SOURCE_TRACEABILITY.md) |
| Kiểm tra 46 rule community | [ROBONUGGETS_46_RULE_MAP.md](standards/ROBONUGGETS_46_RULE_MAP.md) |
| Triển khai cùng Claude/Codex/AGY | [adapters/](adapters/CAPABILITY_MATRIX.md) |
| Viết test/baseline | [EVALUATION_STANDARD.md](standards/EVALUATION_STANDARD.md), [evals/RUNBOOK.md](evals/RUNBOOK.md) |
| Kiểm soát permission hoặc hooks | [SECURITY_AND_PERMISSIONS.md](standards/SECURITY_AND_PERMISSIONS.md) |
| Muốn tạo Skill mới | `python3 studio.py new ...`, sau đó dùng [Skill factory](skills/skill-creator-studio/SKILL.md) |

## Nguồn và giới hạn

Tham khảo trực tiếp: [Agent Skills Specification](https://agentskills.io/specification), [Claude Skills](https://code.claude.com/docs/en/skills), [Anthropic Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices), [OpenAI Build Skills](https://learn.chatgpt.com/docs/build-skills), [Google Antigravity Skills](https://www.antigravity.google/docs/skills), [robonuggets/skill-creator-plus](https://github.com/robonuggets/skill-creator-plus), video [VQyYzLJ6xos](https://www.youtube.com/watch?v=VQyYzLJ6xos) và PDF người dùng cung cấp *The 10 SKILL Rules* (trang 3–10). Xem [source traceability](standards/SOURCE_TRACEABILITY.md) trước khi diễn đạt bất kỳ đề xuất nội bộ nào như một chuẩn chính thức.

Giấy phép: **MIT** ([LICENSE](LICENSE), quyết định 12/10/2026, xem [LICENSE_POLICY.md](LICENSE_POLICY.md)). Repo này **không sao chép mã nguồn của RoboNuggets**; các scripts ở đây được tự triển khai theo tiêu chí kiểm tra công khai. Nội dung public có thể thay đổi sau 12/10/2026; kiểm tra lại trước khi nâng bản lớn. Không có xác nhận đã chạy Claude/Codex/Antigravity thật trong bản phân phối offline này.

## 🤝 ACD Ecosystem Integration

Repo là Studio nhóm 2 — xưởng nền (Skill Factory) trong hệ thống nhiều repo ACD, nhận `production-brief.md` có khối Skill Spec và trả báo cáo AUDIT, diff cùng kết quả validate/eval cho repo sở hữu skill. Khai báo đủ 5 dòng (Role, Upstream, Downstream, Bundles, Handoff) tại [ECOSYSTEM.md](ECOSYSTEM.md).

## Author

**Nguyễn Quang Đức** (Tobi) — founder and CEO of KPIM and co-founder of COMPA Class; Data/AI practitioner and instructor in Vietnam.

Website: https://ducnguyen.vn · GitHub: [@ducnguyen221](https://github.com/ducnguyen221) · Contact: ducnguyen.ams@gmail.com
