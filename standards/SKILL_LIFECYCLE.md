# Skill Lifecycle — Quy trình quản trị phiên bản

## Bốn trạng thái

- **Draft:** mới scaffold, chưa có đầu vào thật và eval.
- **Candidate:** đúng chuẩn portable và static lint pass, 3 scenarios, review ngữ nghĩa hoàn tất; chuẩn bị chạy trên agent thật.
- **Production:** có bằng chứng eval trên runtimes mục tiêu, owner signoff, không có safety blocker.
- **Deprecated:** dừng kích hoạt, lưu changelog/migration path, không xóa đột ngột nếu có người dùng.

## Luồng NEW → AUDIT → REFINE → RELEASE

1. Frame job (phạm vi, input/output, side effects, trigger + không trigger).
2. Viết tối thiểu 3 test prompts và baseline no-skill khi thực thi được.
3. Chọn Single-file / Bundle / Router, mức freedom từng bước.
4. Scaffold bằng `studio.py new` và hoàn thiện references/scripts/assets.
5. `studio.py validate` + manual audit 13 rules/46 community checks.
6. Chạy evals fresh-session, điều chỉnh nội dung dựa trên failure chứ không chỉ làm dài file.
7. Tạo change summary, security review nếu có side effect.
8. Package một Skill, install thử đúng agent, smoke test, chủ sở hữu approve publish.
9. Sau vận hành, thu thập failure và refine; test regression, version bump và rollback nếu cần.

## Phiên bản / breaking changes

- PATCH: sửa typo, link, thông điệp không đổi hành vi.
- MINOR: thêm optional workflow hoặc reference, bổ sung eval.
- MAJOR: đổi trigger, output contract, quyền thực thi hoặc flow rủi ro.

Với thay đổi `description`, phải xem overlap với thư viện skills. Với thay đổi `scripts/`, test các case và dependency. Cần đối chiếu source/vendor update theo ngày; một đường dẫn docs không phải chứng cứ rằng tính năng giữ nguyên mãi mãi.

## Change control

AUDIT là chế độ read-only. REFINE chỉ sửa file sau yêu cầu trực tiếp của owner hoặc approval với những thay đổi đề xuất. Thay đổi phải có diff/rationale/rule IDs, dấu vết test và rollback/previous commit. Không tự động sửa mọi WARN vì WARN có ngoại lệ hợp lý.
