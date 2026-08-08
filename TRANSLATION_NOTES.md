# Translation Notes

Ghi chú dịch thuật cho bản Việt hóa. Tài liệu này là nguồn tham chiếu về quy
tắc dịch và cách xử lý các thuật ngữ cố định, dành cho người dịch và người
duy trì dự án. README.md mô tả cách dùng công cụ; tài liệu này mô tả *dịch thế
nào cho đúng*.

## Translation rules (Quy tắc dịch)

- **`translations.json` là nguồn duy nhất.** Không chỉnh sửa trực tiếp
  file game; mọi thay đổi đi qua bảng dịch rồi `apply.py` / `build_patch.py`.
- **Giữ nguyên tên riêng, placeholder và markup kỹ thuật.**
  - Tên riêng (nhân vật, địa danh, tên sự vật) thường giữ nguyên bản Latinh,
    trừ khi có cách phiên âm/tên thuần Việt đã phổ biến.
  - Placeholder `{0}`, `{1}`, ... và mã `<d>` trong chuỗi **bắt buộc giữ
    nguyên**, không được bỏ sót hay đổi thứ tự.
  - Văn bản credit/license giữ nguyên bản gốc.
- **Thuật ngữ phải thống nhất theo glossary**. Cùng một khái
  niệm tiếng Anh phải dùng cùng một từ tiếng Việt ở mọi nơi, kể cả giữa
  dialogue, menu và mô tả vật phẩm/kỹ năng.
- **Thuật ngữ mơ hồ / cần giải thích** thì thêm dòng `TL Note: ...` ngay dưới
  bản dịch để người đọc hiểu nghĩa ẩn dụ hoặc chú giải của từ (xem ví dụ
  `Wedge` → `Cái Nêm`).
- **Nhịp xuống dòng.** Giữ độ dài dòng gần với bản EN để đồng bộ hội thoại và
  highlight; dùng F3 trong TUI editor để auto-wrap theo chiều rộng chuẩn. Cụm
  từ mang marker `{c:}`/`{w:}`/`{b:}`/`{p}` không được tách nửa ra hai dòng.
- **Không tự ý thêm/xóa `{p}`.** Dấu `{p}` là vị trí chèn tên người chơi, do
  game chèn lúc runtime; chỉ được di chuyển đến đúng vị trí tên người chơi
  xuất hiện trong câu, không xóa tùy tiện.
- **Voice-sync (`times_`) hiếm khi cần đụng tay.** Mỗi dòng thoại có thể có
  một số marker `times_` đánh dấu điểm chữ hiện dừng để khớp nhịp với giọng:
  mỗi marker mang thời gian nghỉ (giây) và vị trí ký tự trong text. Cách đọc
  trong editor:
  - Preview hiện dòng **`Sync:`** (vd `@8 1.00s wait  @40 2.00s`) liệt kê các
    marker của dòng đang mở.
  - Dòng **`VN (plain):`** tô nền xanh nhạt đúng **dấu câu** nơi chữ dừng
    (thường là `.`, `,`, `...`). Khi bật **F4 (EN+)**, dòng EN cũng được tô
    tương tự. Nếu điểm dừng tô nhầm vào chữ thường giữa từ là dấu hiệu offset
    bị lệch.
  - Thanh stats dưới editor có **`before cursor Nch`**: số ký tự (không tính
    xuống dòng) trước con trỏ, dùng để nhập offset thủ công; đặt con trỏ đúng
    chỗ dừng rồi đọc số này.
- **Sửa bằng tay qua F9.** Nhấn **F9** mở panel liệt kê từng marker với ô
  offset có thể chỉnh. Mỗi marker có `@time ...s` (thời gian nghỉ, chỉ đọc).
  Điểm ngắt thường là dấu câu; offset nhập vào là **vị trí của dấu câu đó**
  (lấy từ `before cursor` khi đặt con trỏ vào dấu câu). Bấm **Save** để ghi
  vào `tag_overrides.json` (key `times_`), preview cập nhật ngay; sau đó phải
  **rebuild patch** để game nhận thay đổi. Chỉ chỉnh khi remap tự động đặt sai
  chỗ — bản dịch giữ nguyên dấu câu và nhịp câu thường không cần đụng tới.

## The Captain (Gran/Djeeta)

The Captain là nhân vật chính do người chơi chọn giới tính (Gran/Djeeta).
Cách xưng hô trong tiếng Việt cần trung tính về giới, theo quy tắc sau:

- **Mặc định: `thuyền trưởng`.** Trong phần lớn lời thoại, nhất là khi các
  thành viên phi hành đoàn Grandcypher gọi The Captain, dùng `thuyền trưởng`.
- **Trường hợp đặc biệt: `đội trưởng`.** Khi The Captain giữ vai trò chỉ huy
  một nhóm/cấp trên của một đội cụ thể (nhiệm vụ, đội hình, sự kiện), có thể
  dùng `đội trưởng` thay cho `thuyền trưởng`.
- **Tránh dùng `Anh` (nam tính).** Vì Captain có thể là nữ, từ xưng hô nam
  tính "Anh" là phương án không mong muốn; chỉ giữ lại khi ngữ cảnh bắt buộc
  (câu đã đóng băng trong bản gốc). Các trường hợp còn sót "Anh" đang được rà
  lại dần.
- Khi câu đề cập Captain ở ngôi gián tiếp ("the captain") cũng dịch là
  `thuyền trưởng` (không hoa hóa đầu câu giữa chừng, chỉ viết hoa khi bắt đầu
  câu).

## Writing conventions

- File README/CHANGELOG viết bằng tiếng Anh; tài liệu hướng dẫn dịch
  (file này) viết bằng tiếng Việt để người dịch tra cứu nhanh.
- Mỗi thay đổi dịch lớn nên ghi vào CHANGELOG.md và cập nhật manifest nếu đụng
  tới table (`build_patch.py` / `verify.py` sẽ nhắc).

## TODO
