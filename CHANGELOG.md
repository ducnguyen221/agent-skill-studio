# Changelog

## Chưa phát hành

- Thêm manifest plugin (`.claude-plugin/`, `.codex-plugin/`) và test đồng bộ version giữa các manifest.
- Thêm log chạy phiên mới cho NEW / AUDIT / REFINE trên Claude Code, Codex và Antigravity (`evals/skill-creator-studio/runs/`): luồng công cụ đạt, skill chưa được kích hoạt tự động và chưa chạy baseline không-skill, nên `model_evaluated` vẫn `false`.
- **agent-skill-studio:SPR-01 TK3 (chưa phát hành):** `package`/`install` thôi duyệt bằng `rglob`; gặp cloud, link, trần duyệt hoặc thư mục tên vùng thì ERROR mã mới `PACK` (không gói thiếu im lặng) và đọc file qua `open_nofollow_read`; cloud nhận thêm qua tag reparse `IO_REPARSE_TAG_CLOUD*` nên báo đúng nhãn cloud; `PINNED` một mình không còn là placeholder; `fmt --fix` tạo `.bak` độc quyền (không ghi xuyên link cài sẵn, lỗi giữa chừng không xoá file cài sẵn) và báo `skipped (link)` cho symlink thư mục trên POSIX.
- **agent-skill-studio:SPR-01 TK4 (chưa phát hành):** `install` thoát 2 khi gốc skill (hoặc thư mục cha dưới HOME/workspace) là symlink/junction, nêu đích thật; cờ mới `--allow-root-link` cho phép có chủ ý. Đích là link sống hoặc dangling → thoát 1 `symlink destination refused` (hết traceback). **Đổi hợp đồng:** bản sao lưu của `--force` chuyển từ `<tên>.backup-<UTC>` cạnh skill sang `<cha gốc skill>/.skill-studio-backups/<tên>-<UTC>/` (ngoài gốc skill); khác ổ đĩa chép rồi xoá. Chép file khi cài qua `open_nofollow_read` + `create_exclusive`.
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
