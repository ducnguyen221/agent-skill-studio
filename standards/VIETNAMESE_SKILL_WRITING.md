# Chuẩn viết tiếng Việt cho skill

> **Kết luận:** thân `SKILL.md` dùng đúng một ngôn ngữ, Việt hoặc Anh; frontmatter luôn tiếng Anh. Chuẩn này thêm 14 quy tắc cho thân Việt, trên nền [SKILL_AUTHORING_STANDARD.md](SKILL_AUTHORING_STANDARD.md).

**Phiên bản:** 0.1.0 · **Ngày:** 2026-10-22 · Áp cho skill mới và skill sprint đụng. Skill cũ chỉ báo qua `doctor`.

## Cách dùng

- Lint `VI1`–`VI5` chỉ chạy khi thân có ít nhất 3 % chữ cái có dấu. Thân tiếng Anh không bị báo mã `VI*`.
- Mọi mã `VI*` là cảnh báo (WARN). Dòng có `<!-- studio:vi-ok -->` được miễn.
- Nhãn `[máy: VIn]` là mã lint kiểm quy tắc. Nhãn `[review]` cần người hoặc agent đọc.
- Nguồn `[nội bộ]` là quy ước của Studio, không phải yêu cầu của nhà cung cấp.
- Tiếng Việt tốn token hơn tiếng Anh (×2,14 theo cl100k, ×1,19 theo o200k, trên 3 đoạn mẫu). Tokenizer Claude chưa đo (`not_run`).

## Quy tắc

- **V01** Đặt kết luận trước, tối đa hai câu, ở đầu file. Vì sao: agent bị cắt ngữ cảnh vẫn giữ ý chính. [review] [nội bộ]
- **V02** Mỗi mục một việc, mỗi bước bắt đầu bằng động từ mệnh lệnh ("Chạy lệnh kiểm", không "Việc kiểm tra"). Vì sao: danh từ hoá làm mờ ai làm gì. [review] [nội bộ]
- **V03** Câu tối đa 25 từ, ô bảng tối đa 20 từ; lint chỉ báo khi câu vượt 40 từ. Từ là chuỗi tách bằng khoảng trắng. Vì sao: câu dài làm agent đoán sai chủ ngữ. [máy: VI3] [nội bộ]
- **V04** Viết mệnh lệnh trực tiếp, có chủ ngữ rõ cho mọi điều cấm và bắt buộc ("Cấm sửa…", "Phải chạy…"). Vì sao: câu bị động khó thành hành động. [review] [nội bộ]
- **V05** Lặp danh từ thay cho đại từ khi cách xa hơn một câu ("bộ test", không "nó"). Vì sao: đại từ xa danh từ làm agent gán nhầm đối tượng. [review] [nội bộ]
- **V06** Một khái niệm một từ, theo bảng thuật ngữ bên dưới. Vì sao: đổi từ giữa chừng khiến agent tưởng là hai khái niệm. [review] [nội bộ]
- **V07** Nhãn và trạng thái lấy từ một tập đóng, ví dụ đạt, không đạt, chưa chạy, không áp dụng. Vì sao: mỗi nơi một kiểu thì so khớp chuỗi bị lệch. [review] [nội bộ]
- **V08** Tối giản ngữ cảnh: không lịch sử, không lý do dài, không lặp luật đã ở file khác; chỉ link. Vì sao: mỗi dòng thừa tốn token mỗi lần nạp skill. [review] [nội bộ]
- **V09** Dùng đủ dấu, chữ dựng sẵn NFC; cấm tiếng Việt không dấu và gõ Telex hoặc VNI thô (ngoại lệ: tên file, ID, URL). Vì sao: không dấu gây đồng âm. Máy chỉ kiểm NFC. [máy: VI1] [nguồn: `platform.claude.com/docs/en/build-with-claude/multilingual-support`]
- **V10** Giữ thuật ngữ kỹ thuật tiếng Anh đã quen, đặt trong backtick nếu là mã; lần đầu ghi "Việt (Anh)" một lần mỗi file. Cấm kiểu "deliver kết quả". Vì sao: Anh hoá câu Việt làm mờ nghĩa. [review] [nội bộ]
- **V11** Ngày theo ISO `2026-10-22`, không `22/10/2026`; số ngăn nghìn bằng khoảng trắng (`5 000`, chốt theo khuyến nghị Fable 22/10); đơn vị cách số một khoảng trắng (`25 KB`). Vì sao: ngày d/m và m/d dễ lẫn. Máy chỉ kiểm ngày. [máy: VI2] [nội bộ]
- **V12** Một dấu một nghĩa: "·" chỉ để liệt kê ngang hàng, "—" tối đa một cặp mỗi câu, số thứ tự cho trình tự. Vì sao: ký hiệu đa nghĩa làm agent đọc nhầm thứ tự. [review] [nội bộ]
- **V13** Frontmatter (`name`, `description`, khoá YAML) viết tiếng Anh; thân và lý do viết tiếng Việt; lệnh, đường dẫn, mã định danh giữ nguyên. `description` có chữ Việt phải còn cụm `Use when`. Vì sao: harness định tuyến skill bằng frontmatter. [máy: VI4] [nguồn: `ngon-ngu-tai-lieu.md` của kpim-skills]
- **V14** Mỗi skill chọn một ngôn ngữ cho thân, không trộn theo mục; ví dụ xấu hoặc tốt là ngoại lệ. Vì sao: luật OpcOS chỉ cho tiếng Việt hoặc tiếng Anh. [máy: VI5] [nguồn: `ngon-ngu-tai-lieu.md` của kpim-skills]

## Thuật ngữ

| Thuật ngữ | Nghĩa |
|---|---|
| cỡ | sprint size |
| tier | nhóm model (giữ tiếng Anh) |
| cổng | gate |
| mục | section |
| bước | step |
| việc | task (`TK`) |
| kiểm | check |
| đạt / không đạt / chưa chạy / không áp dụng | pass / fail / `not_run` / not applicable |
