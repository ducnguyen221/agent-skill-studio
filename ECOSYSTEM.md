# ECOSYSTEM — Agent Skill Studio trong hệ thống ACD

## 🤝 ACD Ecosystem Integration
- **Role in ACD:** Studio thuộc Nhóm 2 — xưởng nền (Skill Factory). Repo cấp chuẩn viết, kiểm định và đóng gói Agent Skills (quy trình NEW / AUDIT / REFINE, `studio.py validate`, bộ evals ngoại vi) cho mọi repo khác trong hệ thống nhiều repo ACD.
- **Upstream Controllers:** 10 Team phòng ban (Nhóm 1) và 6 Studio sản xuất khác (Nhóm 2) — khi cần một skill mới hoặc cần audit/cải tiến skill đang có, họ giao yêu cầu cho xưởng này qua repo điều phối.
- **Downstream Consumers:** repo sở hữu skill (Team hoặc Studio đã đặt yêu cầu) — nhận skill đã qua validate và eval để tự cài, tự phát hành trong repo của mình. Repo này không sửa trực tiếp vào repo đó.
- **Recommended Bundles:** Bundle E — `agent-skill-studio` cùng `agent-agile-team` và `agent-operations-team` (repo `agent-operations-team` dự kiến, chưa tạo).
- **Handoff Artifacts:** đầu vào là `production-brief.md` có khối Skill Spec (tên, mô tả, ca kích hoạt, mức tự do, rủi ro). Đầu ra là báo cáo AUDIT, diff đề xuất, kết quả `studio.py validate --all --require-evals` và kết quả eval, kèm gói skill chỉ gồm file runtime.
