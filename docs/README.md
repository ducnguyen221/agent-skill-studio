# Website của Agent Skill Studio

Thư mục `docs/` là website tĩnh của repo, dựng trên OpcOS Design System dùng chung. Mở `docs/index.html` bằng `file://` là chạy được, không cần máy chủ. Thư mục này không phải skill và không vào gói phát hành (`package` chỉ đóng `skills/`).

## Vai từng phần

| Đường | Vai |
|---|---|
| `index.html`, `about/`, `install/`, `guide/`, `flow/`, `principles/` | sáu trang viết tay (Trang chủ, Giới thiệu, Cài đặt, Cách dùng, Luồng & quy trình, Nguyên tắc), sinh bởi `tools/gen-pages.mjs` |
| `docs/` | trang Docs: các file `.md` của repo dựng thành trang đọc được, do `tools/build-docs.mjs` sinh |
| `assets/ds/` | bản chép của Design System (`site.css`, `site.js`, `ds-lock.json`) và `site.json` là cấu hình riêng của repo; không sửa tay |
| `assets/logo.svg` | chỗ đặt logo |
| `tools/` | công cụ dựng và kiểm site, chép từ xưởng OpcOS (`gen-pages.mjs` là của riêng repo) |

## Dựng lại và kiểm

Chạy tại thư mục `docs/`:

```bash
node tools/gen-pages.mjs                 # sinh sáu trang viết tay
node tools/build-docs.mjs --root .       # dựng lại trang Docs từ các .md đã liệt kê trong site.json
node tools/check-site.mjs --root .       # kiểm bản chép Design System, menu, link, Docs còn tươi
```

Danh sách `.md` hiện ra ở trang Docs nằm ở khoá `docsInclude` của `assets/ds/site.json`; thêm hay bớt tài liệu thì sửa ở đó rồi dựng lại.

## Nâng Design System

Sửa Design System ở xưởng OpcOS (`system/plugin-workshop/templates/site/`), không sửa trong repo. Khi Đức đã duyệt bản mới, chép vào đây bằng `install.mjs --target <repo>/docs --scripts <repo>/docs/tools`, rồi chạy lại ba lệnh trên. `install.mjs` ghi đè `assets/ds/` và các file `tools/` của xưởng, nên kiểm lại phần `docsSource` và `docsInclude` trong `tools/build-docs.mjs` sau khi chép.
