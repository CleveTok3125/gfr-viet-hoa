# Translation Notes

Ghi chú dịch thuật cho bản Việt hóa. Tài liệu này là nguồn tham chiếu về quy
tắc dịch và cách xử lý các thuật ngữ cố định, dành cho người dịch và người
duy trì dự án. README.md mô tả cách dùng công cụ; tài liệu này mô tả *dịch thế
nào cho đúng*.

## Translation rules (Quy tắc dịch)

- **`translations.json` là nguồn duy nhất.** Không chỉnh sửa trực tiếp
  file game; mọi thay đổi đi qua bảng dịch rồi `apply.py`.
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
  - Thanh stats dưới editor có **`offset to type Nch`**: chính là giá trị cần
    nhập vào ô offset trong panel F9 — bằng index (tính cả xuống dòng) trong
    bản dịch thuần của ký tự ngay sau vị trí dừng mong muốn, tức đặt con trỏ vào
    dấu câu thì số hiển thị là index dấu câu **+1** (engine dừng ở `offset-1`).
- **Sửa bằng tay qua F9.** Nhấn **F9** mở panel liệt kê từng marker với ô
  offset có thể chỉnh. Mỗi marker có `@time ...s` (thời gian nghỉ, chỉ đọc).
  Điểm ngắt thường là dấu câu; theo quy ước engine, **offset = ký tự đầu tiên
  SAU điểm dừng** (dừng giữa `offset-1` và `offset`), vậy để ngắt tại dấu câu
  có index P phải nhập `P+1`. Preview/Panel hiển thị offset dạng này và tô
  chính dấu câu P (ở `offset-1`). Bấm **Save** để ghi
  vào `tag_overrides.json` (key `times_`), preview cập nhật ngay; sau đó phải
  **rebuild patch** để game nhận thay đổi. Chỉ chỉnh khi remap tự động đặt
  sai chỗ — bản dịch giữ nguyên dấu câu và nhịp câu thường không cần đụng
  tới.

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
  tới table (`verify.py --gen` sẽ nhắc).

## Báo cáo tiến độ (Progress report)

Bảng theo dõi trạng thái hoàn thành từng chương. Đánh dấu `x` vào ô đã hoàn
thành, để `-` cho mục chưa làm.

| Chapter (EN)                     | Chương (VI)                            | Hội thoại  | Highlight  | Voice-sync (times_)  | Glossary (gần nhất)  | Đảm bảo chất lượng  |
|--------------------------------- |--------------------------------------- |:---------: |:---------: |:-------------------: |:-------------------: |:------------------: |
| `Into the Conflux`               | Vào Conflux                            |     x      |     x      |          x           |          x           |          x          |
| `Echoes of Scorn`                | Những Tiếng Vọng Khinh Miệt            |     x      |     x      |          x           |          x           |          x          |
| `A Trial of Two Eternities`      | Thử Thách Của Hai Cõi Vĩnh Hằng        |     x      |     x      |          x           |          x           |          x          |
| `Ragnalia, the Heralds of Doom`  | Ragnalia, Sứ Giả Của Diệt Vong         |     x      |     x      |          x           |          x           |          x          |
| `Becoming Fatebreakers`          | Trở Thành Kẻ Phá Số Mệnh               |     x      |     x      |          x           |          x           |          x          |
| `Every End Has a Beginning`      | Mọi Kết Thúc Đều Có Khởi Đầu           |     x      |     x      |          x           |          x           |          x          |
| `My Power Is Yours`              | Sức Mạnh Của Em Là Dành Cho Mọi Người  |     x      |     x      |          -           |          -           |          -          |
| `Bursting with Power`            | Tràn Đầy Sức Mạnh                      |     x      |     x      |          -           |          -           |          -          |

- **Hội thoại:** toàn bộ dialogue của chương đã dịch.
- **Highlight:** mục `highlight_decisions.json` / `tag_overrides.json` cho các dòng trong
  chương đã được rà soát và khớp với text hiện tại.
- **Voice-sync (times_):** các marker `times_` đã kiểm tra (chỉ cần đụng tay
  khi remap tự động đặt sai điểm ngắt; xem quy tắc F9 ở trên).
- **Glossary:** thuật ngữ của chương (tên riêng, kỹ năng, địa danh) đã thống
  nhất theo glossary.
- **Đảm bảo chất lượng:** văn phong tự nhiên, marker/`{p}` giữ nguyên, dòng
  dài khớp bản EN để đồng bộ highlight và hội thoại.

## TODO

### Tiếp tục

```text
FILE      : text_scenario_730.msg
  BASE      : text_scenario_730
  IDS       : SNT_VT731150_001000
  SPEAKER   : Lyria
  SPEAKERS  : {"SNT_VT731150_001000": {"chara": "NP0000", "voice": "VO_VT731150_NP0000_001000", "listener": 0, "emotion": 2, "name_ja": "ルリア", "name_en": "Lyria"}}
  EN        : "I'll help with my summoning powers! \nI just need some time..."
  VN (plain): "Tôi sẽ hỗ trợ bằng sức mạnh triệu hồi!\nChỉ cần cho tôi chút thời gian..."
  COMPOUND  : "Tôi sẽ hỗ trợ bằng sức mạnh triệu hồi!\nChỉ cần cho tôi chút thời gian..."
  HIGHLIGHTS: []
  PLAYER_POS: null
  DECISIONS : {}
  OVERRIDES : {}
```
