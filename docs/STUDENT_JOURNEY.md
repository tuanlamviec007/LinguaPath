# Lưu nháp và hành trình học của sinh viên

## Hành vi mới

1. Bắt đầu một bài luyện. Nếu tài khoản đã có lượt đang làm hợp lệ của bài đó, hệ thống tiếp tục lượt ấy.
2. Chọn phương án. Trình duyệt chờ khoảng 500 ms rồi gửi bản nháp; màn hình báo đang lưu, đã lưu hoặc lưu lỗi. Có nút lưu thủ công.
3. Rời trang, quay lại Tổng quan và chọn **Tiếp tục bài đang làm**. Lựa chọn đã lưu được khôi phục; phần trăm đúng/đáp án chưa được trả về từ bản nháp.
4. Nộp bài để chấm khi bản nháp còn đồng bộ. Trình duyệt chờ xác nhận lần lưu đang chạy và gửi phiên bản hiện tại; tab cũ nhận thông báo xung đột thay vì ghi đè. Lựa chọn trên form ưu tiên hơn bản nháp; nộp lại cùng lượt đã hoàn thành dẫn về cùng kết quả.
5. Có thể chủ động **Dừng lượt và xóa nháp**, sau đó bắt đầu một lượt mới.

Chỉ phần đã lưu thành công mới khôi phục được khi đóng trang. Nếu mất mạng hoặc hết phiên đăng nhập, màn hình giữ cảnh báo chưa lưu. Hai tab cùng sửa không được ghi đè âm thầm: bản cũ bị chặn và cần tải lại bản đã lưu. Khi quay lại bằng Back/Forward cache, trang cũng yêu cầu tải lại; không tự lưu lại trạng thái cũ. Không có hợp nhất xung đột tự động hoặc chế độ học ngoại tuyến.

## Ranh giới dữ liệu và quyền riêng tư

- Bản nháp nằm trong `AttemptDraftAnswer`, tách khỏi `AttemptAnswer` đã chấm. Không có trường điểm hoặc đúng/sai trong bản nháp.
- Mỗi thao tác kiểm tra tài khoản sở hữu, trạng thái đang làm, câu thuộc lượt làm và phương án thuộc đúng câu; có CSRF và giới hạn payload.
- Mỗi tài khoản/bài chỉ có một lượt `in_progress`, được bảo vệ bằng ràng buộc cơ sở dữ liệu.
- Fingerprint được chốt khi bắt đầu. Thay đổi câu chữ, phương án, đáp án hoặc danh sách câu sẽ làm lượt cũ không còn hợp lệ; hệ thống đóng lượt và bỏ bản nháp thay vì chấm bằng nội dung khác.
- Draft không cản admin xóa câu/phương án. Dữ liệu nháp tương ứng được xóa; dữ liệu bài đã chấm vẫn giữ cơ chế bảo vệ hiện có. Lượt đang làm được kiểm tra lại khi tiếp tục/lưu/nộp.
- Từ M1, kết quả mới lưu snapshot câu chữ, lựa chọn và lời giải khi nộp; sửa nguồn không làm đổi nội dung đã chấm. Kết quả trước migration 0018 được đánh dấu chưa có bản gốc; không tự backfill bằng học liệu hiện tại. Xem [bản ổn định M1](STABILITY_M1.md).

## Tổng kết học tập

Dashboard và trang Tiến độ hiển thị bảy ngày gần nhất gồm lượt luyện đã nộp và lượt ôn từ của chính tài khoản, theo múi giờ đang cấu hình. Sự kiện tương lai, lượt mới mở, lượt đã dừng và dữ liệu tài khoản khác không được tính.

Chuỗi học tính các ngày liên tiếp đến hôm nay; nếu hôm nay chưa có hoạt động, có thể tiếp tục chuỗi tính đến hôm qua. Cửa sổ lịch sử tối đa 366 ngày. Đây là hoạt động sử dụng website, không phải phép đo trình độ tiếng Anh.

Bảng kỹ năng dùng các bài đã nộp trong 30 ngày, gộp số đúng/tổng câu theo Reading, Listening và Từ vựng. Tính cả câu bỏ trống trong bài đã nộp; khi tổng dưới 5 câu sẽ ghi chưa đủ dữ liệu. Liên kết mỗi kỹ năng mở thư viện tương ứng. Không suy ra số phút học hoặc điểm TOEIC.

## Cập nhật dự án đang dùng

```bash
python manage.py migrate
```

Migration `0009` thêm bản nháp, fingerprint và ràng buộc chống lượt đang làm trùng. Các lượt cũ đang làm nhưng chưa có fingerprint được chuyển sang `abandoned`, giữ bản ghi để bắt đầu lại theo giao thức mới; bài đã nộp được giữ. Sao lưu DB trước khi cập nhật, rồi khởi động lại server. Không cần nạp lại từ vựng hay bài luyện cho tính năng này.

## Kiểm chứng

Kiểm thử Python bao gồm tạo/tiếp tục lượt không trùng, khôi phục lựa chọn, cách ly tài khoản, CSRF, đầu vào lỗi, không lộ điểm từ nháp, nộp có dùng bản nháp, nộp lặp, đóng lượt khi nội dung đổi và admin xóa nội dung có draft.

Sáu kiểm thử Node dùng DOM/fetch mô phỏng kiểm tra phản hồi chuyển sang đăng nhập, hàng đợi lưu khi mạng chậm, lưu thành công, hủy nộp và xác nhận/hủy dừng lượt. Chưa kiểm tra trực quan hoặc chạy trên trình duyệt thật; cần bước này trước khi quảng bá rộng rãi.

```bash
python manage.py test
node --test scripts/test_practice_draft.cjs
```

Kết quả bàn giao: **116/116 test Python và 6/6 test JavaScript đạt**. Django system check không báo lỗi, không thiếu migration. Smoke trên DB sau migration đã xác nhận bắt đầu hai lần vẫn một lượt, lưu/khôi phục 2 trong 4 câu và nộp từ bản nháp; tài khoản/dữ liệu thử được rollback. DB vượt kiểm tra toàn vẹn và khóa ngoại.
