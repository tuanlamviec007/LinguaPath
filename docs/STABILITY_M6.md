# LinguaPath — điền và đối chiếu phiếu duyệt M6

Ngày **25/10/2026**. Tiếp tục C01/C05 bằng biểu mẫu dành cho người duyệt: đọc nguồn, điền checklist/kết luận, tải bản nháp và đối chiếu với nguồn hiện tại trước khi mở lại. Chưa có kết luận chuyên môn mới, chưa thêm nội dung hoặc tự phê duyệt. Không có migration mới; database hiện hành vẫn dùng schema0021.

## Luồng làm việc

1. Trong admin → LearningContent → **Chuẩn bị duyệt pilot**, lọc và chọn1–10 bộ; chọn số mẫu mỗi loại rồi **Mở phiếu để điền nhận xét**. Đáp án/lời giải chỉ được gửi cho staff có quyền đọc cả bốn loại học liệu như M5.
2. Chọn mục cần rà soát. Xem nguyên văn câu/thẻ, passage/script, khóa chấm và lời giải từng lựa chọn, nguồn/quyền, mức tham khảo và phạm vi mẫu. Audio URL chỉ hiển thị văn bản, không tự tải hoặc xác minh âm thanh. Người duyệt vẫn phải nghe và đối chiếu file thực.
3. Điền thông tin người duyệt, ngày, checklist và kết luận từng mục. Sao chép thông tin chung là thao tác chủ động và có giải thích ghi đè; không tự nhận dạng người duyệt, ghi ngày hoặc khẳng định chuyên môn. Các mục không áp dụng cần ghi lý do, tương tự mục chưa đạt. Kết luận cần sửa/chưa đủ thông tin cần giải thích.
4. **Tải phiếu đã điền · JSON** để giữ nhận xét. Trang không dùng localStorage hoặc tự ghi nhận xét vào database; đóng trang trước khi tải có thể mất phần chưa lưu. Có nhắc rời trang khi đang có thay đổi. Phiếu được tải giữ nguyên đề, đáp án, hash nguồn và fingerprint gốc.
5. Mở **Đối chiếu hoặc mở lại phiếu**, tải JSON đã lưu. Có thể xem/tải báo cáo hoặc **Kiểm tra và mở để điền tiếp**. Chỉ phiếu có cấu trúc hợp lệ và khớp nguồn hiện tại mới mở tiếp được. Phiếu khớp nhưng thiếu nhận xét vẫn được tiếp tục.

## Ý nghĩa báo cáo

| Trạng thái | Ý nghĩa |
|---|---|
| `current` | Phiếu có cấu trúc/nhận xét hợp lệ, bằng chứng nguồn khớp phép đọc hiện tại. Không đồng nghĩa đã đủ nhận xét hoặc được duyệt. |
| `stale` | Phiếu tự nhất quán nhưng khác nguồn hiện tại, hoặc nguồn không còn xuất được. Xuất phiếu mới và rà lại phần bị ảnh hưởng. |
| `invalid` | Sai schema, sửa phần bằng chứng mà hash không còn khớp, enum/ngày/kiểu dữ liệu không hợp lệ hoặc kết luận mâu thuẫn. |

`items_complete` chỉ đếm mục đã đủ trường thông tin người duyệt/ngày/kết luận/checklist; cả kết luận cần sửa cũng có thể là một nhận xét đầy đủ. `annotations_complete` không phải chất lượng chuyên môn đạt. `approval_allowed` luôn false. Các mục chưa lấy mẫu trong parent không được chứng nhận bởi mẫu này.

Phiếu chỉ cho sửa `human_review` và checklist của từng item, cùng `human_review` ở đầu phiếu. Không sửa `checklist_template`, selection, nguồn, đáp án, hash hoặc fingerprint. Kết luận: `pass`, `needs_changes`, `insufficient_info`, hoặc null khi còn trống; checklist: `pass`, `fail`, `not_applicable`, hoặc null. Không thể kết luận pass với checklist fail. Tên tối đa200 ký tự, chuyên môn2000, mỗi nhận xét4000. Ngày chấp nhận ISO yyyy-mm-dd hoặc datetime có timezone.

Hash không phải chữ ký: người có thể sửa dữ liệu cũng có thể tính lại hash. Không dùng công cụ này để xác thực danh tính hoặc tính xác thực của một phiếu đã được nguồn ngoài sửa và băm lại. Đối chiếu dùng các SELECT tách nhau, chưa là snapshot khóa đồng thời; giữ đợt biên tập ổn định và kiểm tra lại trước quyết định duyệt.

## Command chỉ đọc

```bash
python manage.py validate_review_packet --input docs/pilot_review_sample_m5.json
python manage.py validate_review_packet --input /tmp/review-annotated.json --output /tmp/review-check.json
```

Không ghi đè báo cáo có sẵn khi chưa dùng `--overwrite`; không cho báo cáo ghi lên chính input. Báo cáo không chép nguyên văn đáp án/nhận xét, chỉ mã mục, trạng thái, tổng số và vị trí vấn đề. Phiếu stale/invalid vẫn xuất báo cáo rồi trả exit code khác0; bản current còn dở trả0. JSON sai cú pháp bị từ chối trước tạo báo cáo. Giới hạn20MiB, độ sâu/số node và số vấn đề trả về; từ chối khóa JSON trùng và số không hữu hạn.

GET admin không chứa đề/đáp án; mở phiếu và upload dùng POST+CSRF. Staff bị thu hồi bất kỳ quyền cần thiết sẽ bị chặn ở lần yêu cầu kế tiếp. Phản hồi private/no-store. File upload được đọc trong request, không nhập vào mô hình dữ liệu; file tạm của framework tuân theo vòng đời request. Trình duyệt có thể giữ bản tải xuống do người dùng lưu. Không gửi dữ liệu sang dịch vụ ngoài, không gọi model.

## Nghiệm thu và phần còn mở

**650 Django tests:642 đạt,8 PostgreSQL-only skip;103/103 JavaScript tests đạt.** Thêm29 tests Django và12 tests JS cho validator, CLI, phân quyền/CSRF, nguồn thay đổi, bảo toàn nhận xét/hash, đầu vào lỗi và thao tác editor. System/schema/projection check, migration drift và collectstatic đạt. Phiếu mẫu M5 được đối chiếu current:44 mục,264 ô checklist,0 mục đủ nhận xét; không tự điền thông tin người duyệt.

Browser QA dùng template thật render từ DB memory: desktop và iframe375px, document rộng360px bằng scrollWidth360px, một h1 và mọi ô editor có nhãn. Đã thử sao chép thông tin kiểm thử và chuyển qua lại giữa hai mục, nhận xét được giữ. Trang báo cáo hiển thị trạng thái khớp nguồn. Đây là QA giao diện tĩnh; backend dùng Django Client, chưa phải browser–Django live E2E/điện thoại thật/screen reader. Toàn bộ36 bảng DB chính được đối chiếu không đổi so với bản M4 restore checkpoint, integrity_check OK. C01/C05 vẫn cần người đủ chuyên môn thực sự điền/chốt phiếu, sửa nội dung và chịu trách nhiệm duyệt. Các điều kiện PostgreSQL/Cloudflare/CI, đánh giá model/holdout và calibration/mastery vẫn giữ mở trong bảng audit.
