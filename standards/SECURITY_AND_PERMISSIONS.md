---
title: "Security & Permissions Standard"
status: active
updated: 2026-10-28
---
# Security & Permissions Standard

## Mục tiêu và ranh giới

Skill là tài liệu hướng dẫn và có thể kèm mã thực thi. **Không được coi Skill là security boundary.** Enforcement phải dựa vào permission của host, sandbox, pre-execution validation và cơ chế phê duyệt. Đặc biệt với Codex/Claude/AGY: không tự động cấp quyền mới chỉ vì Skill đề nghị.

## Threat model

| Nguy cơ | Ví dụ | Biện pháp |
|---|---|---|
| Prompt injection | README/references thu thập từ internet ra lệnh exfiltrate | Xem nội dung tải về là dữ liệu, không là instruction |
| Script supply chain | Download script từ GitHub rồi chạy tự động | Pin source/version/hash nếu cần; review code; cấm run untrusted script tự động |
| Credentials | `.env`, token, service account trong assets | Scan/cấm vào package; dùng secret store của runtime |
| Destructive action | `rm`, `DROP`, deploy production | Dry run / plan / diff / explicit approval / rollback |
| Data exposure | Upload dữ liệu KPIM/COMPA vào cloud trái phép | Data classification, minimization, allowlist đích |
| Hidden evaluator answers | Ship `evals/` vào Skill bundle | Evals ngoài runtime, packager exclude |
| Cross-agent mismatch | Copy Claude `hooks` sang Codex | Cấu hình riêng theo agent ([HARNESSES.md](HARNESSES.md)), host sandbox tests |

## Chính sách action risk

- **Read-only**: agent được xem tài liệu trong scope user đã cấp; không tự thêm connector/network access.
- **Write local / reversible**: tạo file dưới thư mục được phép, show plan/diff khi thay đổi nhiều file; giữ backup/rollback.
- **External side-effect**: gửi email, thanh toán, publish, deploy, chạm production hoặc xóa dữ liệu: yêu cầu quyền cụ thể, gate kỹ thuật và bước xác nhận theo host.
- **Dangerous**: không tự thêm `--force`, `--no-verify`, bỏ qua validation, vô hiệu hóa sandbox/hook để hoàn thành nhanh.

## Cơ chế bảo vệ

1. **Preflight plan**: mô tả file/tài nguyên sẽ bị thay đổi, phạm vi và bước rollback.
2. **Check**: validator/sandbox/policy gate độc lập khỏi lời nhắc ngôn ngữ tự nhiên.
3. **Execute**: chỉ thực thi hành động đã được cấp phép trong scope tương ứng.
4. **Verify**: xác nhận output/sự thay đổi và không có side effect ngoài phạm vi.
5. **Report**: log những gì thực sự đã làm, không tuyên bố quyền chưa được cấp.

Với Claude Code, hook trong SKILL frontmatter có thể sống từ lúc Skill được invocation đến hết session. Vì vậy rules cần bảo vệ **mọi phiên** phải ở quyền/hook/policy toàn cục, không chỉ hook trong Skill. Không assume Codex/Antigravity có schema hook giống Claude Code.

## Bảo mật khi đóng gói

- Packager từ chối symlink, file vượt ra ngoài root Skill, các path `evals/`, `.env`, key/cert và folder `__pycache__`/`.git`.
- Không đưa dataset khách hàng thật vào fixture/test baseline khi không được phép; dữ liệu mẫu phải synthetic.
- Khi script cần package, công bố dependency và version thực sự, chạy cùng quyền tối thiểu.
- Không ghi secrets trong README, SKILL.md, test output hoặc log. Mọi access token phải được truyền qua biến môi trường/secret manager với chính sách runtime.

## Engine không nạp mã từ repo chứa nó

Engine (`studio.py` và các mô-đun cạnh nó) không có cơ chế nạp mã từ repo chứa nó. Engine được chép rời hoặc cài vào cây lạ không biết repo nào là «của nó», nên mọi cổng chỉ đọc dữ liệu (JSON, log, Markdown) và không nạp mã theo vị trí: không theo thư mục làm việc, biến môi trường hay đường dò được. Muốn thêm một cổng cần mã thì mã đó nằm trong chính engine, đi qua review bảo mật.

## Kiểm thử hard-stop (bắt buộc khi Side-effect)

- **Allow case**: tác vụ trong ngưỡng/được duyệt thành công.
- **Deny case**: vượt ngưỡng/không có approval bị chặn trước khi tác dụng xảy ra.
- **Bypass test**: kiểm tra đường chạy khác (command tương đương, tool khác, direct script) không bỏ qua gate.
- **Non-invasive test**: dùng mock hoặc sandbox staging, tuyệt đối không thử chặn bằng giao dịch thật.

## Trước khi chấp thuận PR

- Owner và threat model được xác định.
- Code/script mới đã review, dependency/permissions rõ.
- Không có secret, symlink, link/path traversal.
- Explicitly supported runtimes; no claims of cross-vendor hook portability.
- Có đường rollback và audit trail cho thay đổi có tác động.

**Nguồn:** [Claude Code Hooks](https://code.claude.com/docs/en/hooks), [Claude Skills](https://code.claude.com/docs/en/skills), [Agent Skills Spec](https://agentskills.io/specification).
