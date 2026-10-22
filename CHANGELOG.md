# Changelog

## Chưa phát hành

- Thêm manifest plugin (`.claude-plugin/`, `.codex-plugin/`) và test đồng bộ version giữa các manifest.
- Thêm log chạy phiên mới cho NEW / AUDIT / REFINE trên Claude Code, Codex và Antigravity (`evals/skill-creator-studio/runs/`): luồng công cụ đạt, skill chưa được kích hoạt tự động và chưa chạy baseline không-skill, nên `model_evaluated` vẫn `false`.
- **SPR-33 (chuẩn viết skill v1), chưa phát hành.** Chỉ thêm, không đổi version:
  - Chuẩn viết skill về một dạng: `standards/SKILL_AUTHORING_STANDARD.md` từ 11 135 xuống 5 599 ký tự, bộ rule `SK-00`…`SK-15` (thêm `SK-14` chữ ép buộc phải có lý do, `SK-15` Contents và điều giữ ở đầu); thêm `standards/MEMO-SKILL-V0.md` (memo v0) và `standards/VIETNAMESE_SKILL_WRITING.md` (chuẩn viết thân tiếng Việt).
  - `validate`: mã kiểm mới `FM5`, `FM6`, `FM8`, `CT10`, `DS4`, `DS5`, `ST2`, `ST3`, `ST5`, `ST7`, `ST8`, `SZ1`, `SZ2` và lint tiếng Việt `VI1`–`VI5`; cờ `--target {portable,claude-code}` (14 khoá riêng Claude Code là `FM6` WARN thay vì lỗi).
  - `new --lang {en,vi}` và `--full`; hai template: `templates/skill-template/` (`SKILL.md`, `SKILL.vi.md`) và `templates/skill-template-full/` (kèm `references/PROCESS_TEMPLATE.md`, `scripts/`, `assets/`, `agents/openai.yaml`); hai skill được tối giản theo template.
  - `install --user` cho Codex (`~/.agents/skills`) và Antigravity (`~/.gemini/config/skills`); Claude Code `--user` thoát 2; thiếu thư mục cha cũng thoát 2.
  - `evals --export agentskills`, `doctor` (quét nhiều gốc skill, chỉ báo cáo) và `fmt` (`--check` mặc định, `--fix` tạo `<file>.bak-<ISO>`, `--no-backup`).
  - Thư mục `content/` (mẫu `description`, case eval, hai skill mẫu tiếng Anh và tiếng Việt), `evals/tools/` (`activation.py`, `oracle.py`, `redact.py`), `.gitignore` thêm `.coverage`.
  - Tài liệu trạng thái khớp mã: `README.md`, `QA_REPORT.md`, bốn file `adapters/*` (`Checked: 2026-10-23` kèm nguồn), `registry/SKILL_CATALOG.md`, `templates/README.md`, `standards/README.md`. Lô kích hoạt SPR-33 chạy trên Claude Code; `model_evaluated` vẫn `false`.

## 0.1.0 — 2026-10-12

- Khởi tạo Agent Skill Studio, portable Skill factory và template.
- Quy chuẩn 13 rule được đối chiếu với video, PDF RoboNuggets và official docs.
- Thêm các adapter Claude Code, Codex, Google Antigravity.
- Thêm static validator, audit, scaffold, package, install và kiểm tra eval manifest.
- Evals nằm ngoài runtime Skill; tạo ví dụ kiểm tra data quality và bộ test offline.

**Trạng thái:** prototype usable; static checks + unit tests không thay thế model evaluation thực tế.
