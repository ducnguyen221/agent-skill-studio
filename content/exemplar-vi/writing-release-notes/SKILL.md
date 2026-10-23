---
name: writing-release-notes
description: "Drafts release notes from merged pull requests since the last tag. Use when the user asks for release notes or a changelog entry; viết ghi chú phát hành."
metadata:
  version: "1.0.0"
---

# Writing Release Notes

Soạn ghi chú phát hành từ các pull request đã gộp kể từ tag gần nhất. Người dùng thấy ngay điều gì đổi với họ. Mỗi dòng nêu tác động, không kể lại diff.

## Bước

1. Liệt kê các pull request đã gộp kể từ tag gần nhất. Dừng và hỏi nếu repo chưa có tag nào, vì chưa có mốc để so.
2. Nhóm các pull request theo loại: tính năng mới, sửa lỗi, thay đổi phá vỡ, nội bộ.
3. Viết mỗi dòng tối đa 25 từ, bắt đầu bằng động từ và nêu tác động với người dùng.

## Gotchas

- Ghi ngày theo ISO, ví dụ `2026-10-22`, vì ngày kiểu d/m/y dễ bị đọc nhầm thứ tự ngày và tháng.
- Không bịa số pull request. Chỉ ghi số có trong danh sách đã liệt kê; thiếu số thì bỏ số.
