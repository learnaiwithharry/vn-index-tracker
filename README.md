# VN-Index Tracker

Trang theo dõi cá nhân, tự cập nhật sau mỗi phiên giao dịch:

- **Index** – VN-Index không gồm nhóm Vingroup (VIC, VHM, VRE, VPL) so với VN-Index, VN30, VN100.
- **Sector Rotation** – hiệu suất 18 nhóm ngành (ICB cấp 2 theo FiinPro) so với các chỉ số.
- **Tracking SMA** – vị trí của chỉ số, từng ngành và từng mã so với SMA20, SMA50, SMA200.
- **Money Flow** – bảng biến động giá phiên gần nhất, 5 phiên gần nhất và 22 phiên gần nhất của VN30 và từng ngành.

## Cách hoạt động

| Thành phần | Vai trò |
|---|---|
| `scripts/fetch.py` | Tải giá, vốn hóa, sự kiện quyền từ API công khai của VNDirect; rổ VN30/VN100 từ KBS. |
| `data/store/` | Kho dữ liệu lịch sử từ 02/01/2020, lưu ngay trong repo (mỗi tháng một file). |
| `scripts/compute.py` | Tính các chỉ số và ghi ra `site/data.json`. |
| `site/index.html` | Trang web, đọc `data.json`. |
| `.github/workflows/update.yml` | Tự chạy lúc 16:37 và 20:23 (giờ Việt Nam) các ngày thứ Hai đến thứ Sáu, rồi đăng trang lên GitHub Pages. |

## Việc cần làm thủ công

**Khi có mã mới niêm yết trên HOSE.** Trang tự đưa mã vào tính toán và tạm xếp ngành theo ICB công khai, kèm một dòng
cảnh báo màu vàng. Để xác nhận theo FiinPro: mở `data/sectors_fiinpro.csv`, bấm biểu tượng bút chì, thêm một dòng
`MÃ,Tên công ty,Tên ngành L2` (tên ngành phải viết đúng như các dòng có sẵn), rồi bấm **Commit changes**.

**Chạy cập nhật ngay.** Vào tab **Actions** > **Cập nhật dữ liệu và đăng trang** > **Run workflow**.

**Tải lại toàn bộ lịch sử** (khi nghi dữ liệu sai): sửa bước "Tải dữ liệu mới" thành `python scripts/fetch.py --full`,
chạy một lần rồi sửa lại.

## Phương pháp

- Tỷ suất sinh lời của từng mã theo quy ước chỉ số giá, giống VN-Index: có điều chỉnh chia tách, cổ phiếu thưởng,
  cổ tức cổ phiếu; không cộng lại cổ tức tiền mặt.
- Chỉ số ngành: bình quân gia quyền theo vốn hóa. Mã mới niêm yết hoặc chuyển sàn được tính từ phiên thứ hai trên HOSE.
- VN-Index không gồm Vingroup: `r_ex = (r_VNIndex − w × r_Vin) / (1 − w)`, với `r_VNIndex` là biến động của chỉ số
  chính thức và `w` là tỷ trọng vốn hóa của nhóm ở phiên trước.
- Thứ tự cột ngành ở tab Money Flow được chốt theo vốn hóa ngày 13/11/2026 (`data/sector_order.json`).

Trang không phải khuyến nghị đầu tư.
