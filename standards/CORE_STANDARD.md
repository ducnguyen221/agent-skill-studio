---
title: "Core Standard — Nguyên tắc nền tảng của Agent Skill Studio"
status: active
updated: 2026-10-23
---
# Core Standard — Nguyên tắc nền tảng của Agent Skill Studio

**Phạm vi:** mọi Skill được tác giả/kiểm định/phân phối bằng repository này. **Phiên bản:** 0.1.0 — 2026-10-12.

## Contents
- Các thành phần và ranh giới
- Mức độ quy tắc và thẩm quyền
- Kiến trúc chuẩn
- Tính di động và tối ưu context
- Điều kiện xuất bản

## Các thành phần và ranh giới

| Đối tượng | Mục đích | Có được tự động đọc? |
|---|---|---|
| Repo `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` | Hành vi thường trực trong phạm vi mà từng runtime hỗ trợ | Theo cơ chế discovery của runtime, **không mặc định chung** |
| `SKILL.md` | Nhiệm vụ, điều kiện kích hoạt, workflow, routing và Definition of Done | Chỉ khi Skill được chọn / gọi theo runtime |
| `references/` | Tài liệu chuyên đề bổ sung | Theo nhu cầu, nếu Skill chỉ ra đúng file |
| `scripts/` | Thực thi thao tác có thể kiểm tra bằng code | Không tự chạy chỉ vì tồn tại; agent phải thực sự gọi tool |
| `assets/` | Mẫu, logo, cấu hình, dữ liệu mẫu và những file dùng tạo đầu ra | Chỉ khi tác vụ sử dụng |
| `evals/<skill-name>/` | Test trigger, kết quả, regression, evidence | **Không** phân phối cùng Skill mặc định |
| `standards/` | Quy định cách tạo, kiểm định và phát hành Skill | Tài liệu tác giả, không chèn nguyên gói vào runtime Skill |
| `adapters/` | Khác biệt Claude, Codex, Antigravity | Đọc đúng adapter theo đích, không giả định đồng nhất |

**Từ khóa:** Rule = chỉ dẫn; Skill = gói khả năng; Tool/Script = phương tiện thực thi; Hook/Policy = cơ chế kiểm soát ngoài văn bản; Eval = bài kiểm định hành vi; Asset = tài nguyên phục vụ đầu ra.

## Mức độ quy tắc và thẩm quyền

- **MUST:** bắt buộc theo tiêu chuẩn Studio. Nếu bỏ qua, phải báo lỗi hoặc có ngoại lệ đã được owner phê duyệt.
- **SHOULD:** khuyến nghị mạnh; khi không áp dụng phải ghi rõ vì sao và dữ liệu hỗ trợ ngoại lệ.
- **MAY:** tùy chọn dựa trên nhu cầu.
- **CONDITIONAL MUST:** trở thành bắt buộc khi có điều kiện rủi ro/tác vụ đã nêu.
- `Official` trong source matrix là sự kiện/đặc tả do nhà cung cấp công bố, **không** đồng nghĩa rule đó vốn đã được họ gắn nhãn MUST.
- Số dòng 500 của `SKILL.md` và mục lục reference >100 dòng là **best practice**, chưa phải ràng buộc cứng trong Agent Skills Specification.

**Nguồn quyền hạn:** nội dung của file repo không thể ghi đè system/developer policy của runtime, quyền hệ điều hành hoặc sự đồng ý của người dùng. `AGENTS.md` và `CLAUDE.md` có thể xung đột; ranh giới tác dụng do runtime quyết định. Xem `RULES_AND_PRECEDENCE.md` và adapter.

## Kiến trúc chuẩn

Một Skill tối thiểu có `SKILL.md` với YAML frontmatter `name` và `description` hợp lệ. Các thư mục khác chỉ thêm nếu chúng phục vụ nhiệm vụ cụ thể. Không tạo `scripts/` hoặc `assets/` rỗng chỉ để đủ sơ đồ.

Quy định bắt buộc của Studio:

1. Mỗi Skill có đúng một chức năng/nhóm nhiệm vụ được mô tả bằng ngôn ngữ người sử dụng.
2. Core entrypoint dùng sáu trường frontmatter chuẩn tương thích khi cần portable: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` (hai trường đầu bắt buộc).
3. Hướng dẫn dài hoặc hiếm dùng đưa vào `references/`, link từ `SKILL.md` với điều kiện mở rõ ràng.
4. Mỗi script có mục đích, input, output, error handling và chính sách dependency được công bố.
5. Không nhân bản các quy tắc giống nhau ở mọi file, không giấu quy tắc bắt buộc trong example/asset không được đọc.
6. Evals độc lập được dùng để kiểm thử Skill trước khi nâng production.
7. Quy tắc quan trọng cần enforced bằng công cụ phù hợp, không chỉ được yêu cầu trong prompt.

## Tính di động và tối ưu context

- `SKILL.md` là router; **một mô tả dài không thay được trigger chính xác**.
- Dùng reference trực tiếp, nhất quán tên thuật ngữ và một mặc định + ngoại lệ thực sự cần.
- Nêu lý do tại sao một quy tắc tồn tại; không bổ sung sự kiện dễ lỗi thời vào quy tắc bất biến.
- Không giả định script có mạng, thư viện đã cài, key đã cấp hoặc filesystem giống máy tác giả.
- Khi chuyển Skill sang môi trường mới, thiết lập quyền (permission, sandbox, hooks, approvals) **riêng**, không sao chép lệnh tự động tắt bước xác nhận.

## Điều kiện xuất bản

- Static validator PASS mọi ERROR; warning được xử lý hoặc chấp nhận có lý do.
- Test metadata có >=3 tình huống thực tế gồm ít nhất một negative trigger.
- Tất cả fixtures/kết quả kiểm thử không có trong package runtime.
- Skill có quyền thực thi nguy hiểm chỉ được publish sau khi policy độc lập và allow/deny test thực tế đều PASS.
- Mọi nhận định về "model tested" phải có log, ngày, phiên bản, prompt và kết quả. Định nghĩa: [Không pass giả](EVALUATION_STANDARD.md#không-pass-giả-not_run).
- Có chủ sở hữu, phiên bản, cách rollback và changelog khi Skill được sử dụng cho production.

## Links

- [Agent Skills Specification](https://agentskills.io/specification)
- [Claude Skills](https://code.claude.com/docs/en/skills)
- [Codex build skills](https://learn.chatgpt.com/docs/build-skills)
- [Antigravity Skills](https://www.antigravity.google/docs/skills)
