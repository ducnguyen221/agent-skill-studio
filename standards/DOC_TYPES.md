---
title: "Doc Types — luật cho ba loại tài liệu"
status: active
updated: 2026-10-28
---
# Doc Types — luật cho ba loại tài liệu

> **Kết luận:** tài liệu agent đọc thuộc ba loại, mỗi loại một bộ luật: skill, workflow / quy trình, file luật agent. Loại được nhận từ khoá `type:` ở frontmatter (`skill`, `workflow` hay `rules`), rồi từ tên file; không nhận được loại nào thì `check` thoát 2, không đoán. Máy kiểm theo file này thuộc chặng 3; trước đó người soạn và reviewer tự kiểm theo từng dòng dưới đây.

## Skill

- **Nhận loại:** tên file `SKILL.md`. Không ghi `type:` trong frontmatter của skill: `SK-00` chỉ cho sáu khoá portable, khoá lạ là lỗi `FM4`.
- **Bắt buộc:** frontmatter `name` và `description` đúng `SK-00`; việc skill làm, khi nào dùng, và phạm vi không kích hoạt; các luật `SK-*` mức MUST, kể cả «MUST nếu …» khi điều kiện đúng với skill đó.
- **Cấm:** khoá frontmatter ngoài `SK-00` (như `version:`, `triggers:`); secret; đường dẫn cứng của máy tác giả; lệnh tắt sandbox hay xác nhận; fixture và kết quả eval trong gói runtime.
- **Giới hạn:** theo `SK-*`: thân `SKILL.md` <500 dòng và <5 000 token (`SK-01`), `name` ≤64 ký tự, `description` ≤1 024 ký tự (`SK-00`), reference >100 dòng có `## Contents` (`SK-15`).

## Workflow / quy trình

- **Nhận loại:** `type: workflow` ở frontmatter, hoặc file nằm trong thư mục `workflows/`.
- **Bắt buộc:** một câu **Kết luận** ở đầu (việc này làm gì, kết quả ra sao); các **Bước** đánh số, mỗi bước kiểm được; mục **Xong khi** nêu điều kiện kiểm được và đường quay lại khi kiểm lỗi (`SK-06`).
- **Cấm:** bước không có cách kiểm; nhật ký hay lịch sử thay đổi; chép lại luật đã có ở nơi khác (link thay chép, `SK-02`); bước nguy hiểm không có cổng thật (`SK-10`); secret.
- **Giới hạn:** ≤ 300 dòng; dài hơn thì tách phần hiếm dùng sang file được link kèm khi nào đọc.

## File luật agent

- **Nhận loại:** tên file `AGENTS.md`, `CLAUDE.md` hay `GEMINI.md`; hoặc `type: rules` ở frontmatter cho file luật tên khác (ví dụ trong `.agents/rules/`, `.claude/rules/`).
- **Bắt buộc:** chỉ luật đang hiệu lực, mỗi luật nêu được lý do hoặc phạm vi; `AGENTS.md` là bản nguồn, `CLAUDE.md` nạp nó bằng `@AGENTS.md` và `GEMINI.md` trỏ về `AGENTS.md` ([HARNESSES.md](HARNESSES.md)); mục kiểm trước khi báo xong nếu repo có lệnh kiểm.
- **Cấm:** lịch sử đổi luật, ngày «đổi từ bản X», mã commit; khối lệnh dùng để chạy ngay (lệnh thuộc README của thành phần), ngoại lệ duy nhất là mục kiểm trước khi báo xong, tối đa 5 lệnh; secret; luật tắt sandbox hay xác nhận của host.
- **Giới hạn:** ≤ 200 dòng; file luật dùng chung cho nhiều agent thì giữ một bản và để các file còn lại trỏ về.
