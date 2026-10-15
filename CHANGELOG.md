# Changelog

## Chưa phát hành

- Thêm manifest plugin (`.claude-plugin/`, `.codex-plugin/`) và test đồng bộ version giữa các manifest.
- Thêm log chạy phiên mới cho NEW / AUDIT / REFINE trên Claude Code, Codex và Antigravity (`evals/skill-creator-studio/runs/`): luồng công cụ đạt, skill chưa được kích hoạt tự động và chưa chạy baseline không-skill, nên `model_evaluated` vẫn `false`.

## 0.1.0 — 2026-10-12

- Khởi tạo Agent Skill Studio, portable Skill factory và template.
- Quy chuẩn 13 rule được đối chiếu với video, PDF RoboNuggets và official docs.
- Thêm các adapter Claude Code, Codex, Google Antigravity.
- Thêm static validator, audit, scaffold, package, install và kiểm tra eval manifest.
- Evals nằm ngoài runtime Skill; tạo ví dụ kiểm tra data quality và bộ test offline.

**Trạng thái:** prototype usable; static checks + unit tests không thay thế model evaluation thực tế.
