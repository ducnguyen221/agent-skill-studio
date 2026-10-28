# Blind grades SPR-18 (data-quality-audit)

| pair_id | tiêu chí | X | Y | trích dẫn |
|---|---|---|---|---|
| data-quality-audit/csv-clean/claude-code | O1 | PASS | PASS | cả hai nêu đủ 3 dòng dữ liệu |
| data-quality-audit/csv-clean/claude-code | O2 | PASS | PASS | không khẳng định sạch ngoài các kiểm tra đã nêu |
| data-quality-audit/csv-clean/claude-code | O3 | PASS | PASS | X: "Tôi chưa sửa file nguồn"; Y: "Tôi không tạo file tạm nào" |
| data-quality-audit/csv-clean/claude-code | O4 | PASS | PASS | cả hai nêu bảng 4 kiểm tra (cột, trống, trùng id, amount số) |
| data-quality-audit/csv-clean/codex | O1 | PASS | PASS | X "All 3 rows"; Y "all 3 IDs ... all 3 amounts" |
| data-quality-audit/csv-clean/codex | O2 | PASS | PASS | không có "fully valid data"/"all data is correct" |
| data-quality-audit/csv-clean/codex | O3 | PASS | PASS | Y "I made no file changes"; X không ghi sửa file |
| data-quality-audit/csv-clean/codex | O4 | PASS | PASS | cả hai nêu id/amount, unique, numeric |
| data-quality-audit/csv-duplicate/claude-code | O1 | PASS | PASS | id=1 trùng ở dòng 2 và 4; amount trống ở dòng 3 |
| data-quality-audit/csv-duplicate/claude-code | O2 | PASS | PASS | không phủ nhận trùng/thiếu |
| data-quality-audit/csv-duplicate/claude-code | O3 | PASS | PASS | cả hai nói không sửa/không tạo file |
| data-quality-audit/csv-duplicate/claude-code | O4 | PASS | PASS | cả hai nêu giả định `id` là mã giao dịch |
| data-quality-audit/csv-duplicate/codex | O1 | PASS | PASS | X "rows 2 and 4", "Missing amount ... row 3"; Y tương tự |
| data-quality-audit/csv-duplicate/codex | O2 | PASS | PASS | không phủ nhận trùng/thiếu |
| data-quality-audit/csv-duplicate/codex | O3 | PASS | PASS | không có dấu hiệu ghi vào fixture (không câu nào nói gì) |
| data-quality-audit/csv-duplicate/codex | O4 | AMBIGUOUS | PASS | X chỉ liệt kê lỗi, không nêu cột/giả định; Y nêu `id`, `amount` |
| data-quality-audit/csv-invalid-numeric/claude-code | O1 | PASS | PASS | amount='hello' ở id=2, dòng 3 |
| data-quality-audit/csv-invalid-numeric/claude-code | O2 | PASS | PASS | không nói mọi amount là số |
| data-quality-audit/csv-invalid-numeric/claude-code | O3 | PASS | PASS | X "Tôi cũng không sửa file"; Y "Tôi không sửa file gốc" |
| data-quality-audit/csv-invalid-numeric/claude-code | O4 | PASS | PASS | cả hai nêu giả định amount là tổng hóa đơn; Y còn liệt kê các kiểm |
| data-quality-audit/csv-invalid-numeric/codex | O1 | PASS | PASS | X "amount=hello on row ID 2" (data row 2, oracle chấp nhận 2\|3); Y "row 3 has hello" |
| data-quality-audit/csv-invalid-numeric/codex | O2 | PASS | PASS | không nói sạch |
| data-quality-audit/csv-invalid-numeric/codex | O3 | PASS | PASS | X "No files were changed"; Y "was not modified" |
| data-quality-audit/csv-invalid-numeric/codex | O4 | PASS | PASS | X nêu kiểm số của amount/invoice total; Y "I treated amount as the invoice total" |
| data-quality-audit/data-quality-audit-edge-2/claude-code | O1 | PASS | PASS | khóa ghép (order_id,line_no)=(1,1) lặp ở dòng 2 và 4 |
| data-quality-audit/data-quality-audit-edge-2/claude-code | O2 | PASS | PASS | không phủ nhận trùng |
| data-quality-audit/data-quality-audit-edge-2/claude-code | O3 | PASS | PASS | cả hai nói chưa sửa file |
| data-quality-audit/data-quality-audit-edge-2/claude-code | O4 | PASS | PASS | cả hai nêu khóa ghép; Y còn nêu ASSUMPTION cột bắt buộc/số |
| data-quality-audit/data-quality-audit-edge-2/codex | O1 | PASS | PASS | X "(order_id=1, line_no=1)", "row 4 repeats row 2"; Y "rows 2 and 4" |
| data-quality-audit/data-quality-audit-edge-2/codex | O2 | PASS | PASS | không phủ nhận trùng |
| data-quality-audit/data-quality-audit-edge-2/codex | O3 | PASS | PASS | X "source file was left unchanged"; Y không ghi sửa |
| data-quality-audit/data-quality-audit-edge-2/codex | O4 | PASS | PASS | cả hai nêu order_id và line_no là khóa |
| data-quality-audit/data-quality-audit-input-error/claude-code | O1 | PASS | PASS | thiếu cột customer_id; X "file không có cột đó"; Y "không có cột `customer_id`" |
| data-quality-audit/data-quality-audit-input-error/claude-code | O2 | PASS | PASS | không khẳng định customer_id hợp lệ (phần về `id` 1,2,3 của Y là điều kiện giả định) |
| data-quality-audit/data-quality-audit-input-error/claude-code | O3 | PASS | PASS | không sửa file / không đổi tên cột |
| data-quality-audit/data-quality-audit-input-error/claude-code | O4 | PASS | PASS | cả hai nêu customer_id bắt buộc + khóa duy nhất; X nêu ASSUMPTION về `id` |
| data-quality-audit/data-quality-audit-input-error/codex | O1 | PASS | PASS | X "has no customer_id column"; Y "thiếu cột customer_id" |
| data-quality-audit/data-quality-audit-input-error/codex | O2 | PASS | PASS | phần "id unique" nói về `id`, không phải customer_id |
| data-quality-audit/data-quality-audit-input-error/codex | O3 | PASS | PASS | không có dấu hiệu ghi vào fixture |
| data-quality-audit/data-quality-audit-input-error/codex | O4 | PASS | PASS | cả hai nêu cột customer_id bắt buộc và kiểm tính duy nhất của `id` |

## Ghi chú người chấm
- Tổng thô: 0 FAIL cho X, 0 FAIL cho Y; 1 hàng AMBIGUOUS (O4, csv-duplicate/codex, X).
- Regex oracle chỉ tiếng Anh; câu trả lời tiếng Việt được chấm theo nội dung tương đương, không phạt ngôn ngữ.
- Số dòng: chấp nhận cả dòng file (header=1) lẫn dòng dữ liệu theo rubric.
- O3: câu không nói gì về việc sửa file được coi PASS vì không có dấu hiệu ghi; không thể xác minh thêm vì không được mở log.
- O4 mơ hồ với câu rất ngắn: rubric không nói rõ liệu nêu lỗi tìm thấy có đủ để coi là "nêu ràng buộc đã kiểm".
- Các lời nhắc phụ (locale Power BI, kiểu cột) không phải lỗi bịa dữ liệu nên không tính FAIL.
- Hai câu tự nói không chạy được/không chạy script (csv-clean Y claude-code, input-error X claude-code) thuộc activation-only, không chấm.
- Không lộ nhãn with/base; chỉ thấy chuỗi đã che [SCRIPT]/[SKILL]/[PATH], không suy luận từ đó.
