# Luyện lại câu sai — 20/10/2026

## Cách sử dụng

1. Làm và nộp một bài luyện. Các câu sai hoặc bỏ trống được ghi vào Sổ lỗi cá nhân.
2. Mở **Sổ lỗi**, chọn loại lỗi nếu cần, rồi **Bắt đầu lượt ôn**. Hệ thống lấy tối đa 10 câu khác nhau đang cần ôn của kỳ thi trong hồ sơ. Nếu đã có lượt ôn đang làm, hệ thống mở lại chính nhóm câu đó.
3. Trả lời trên trang riêng, chưa hiện đáp án, lời giải hoặc transcript. Reading có đoạn văn; Listening dùng file audio có sẵn. Lựa chọn được tự động lưu sau khoảng 0,5 giây khi thay đổi; có nút Lưu bản nháp và trạng thái xác nhận lưu. Chỉ rời trang sau khi thấy đã lưu nếu muốn tiếp tục ở thiết bị khác. Khi lưu lỗi hoặc chưa có xác nhận, trang cảnh báo để tránh mất lựa chọn.
4. Nộp lượt ôn để xem đúng/sai/bỏ trống và lời giải từng phương án. Câu đúng được đánh dấu đã ôn; câu sai/bỏ trống vẫn cần luyện. Các mục lỗi trùng cùng câu từ trước lúc bắt đầu cũng được đánh dấu khi trả lời đúng. Lỗi mới phát sinh trong lúc làm lượt ôn không tự đóng theo kết quả lượt cũ.
5. Chọn **Ôn tiếp câu cần luyện**, về Sổ lỗi hoặc xem ba lượt ôn gần nhất. Nút ôn tiếp lấy nhóm từ toàn bộ câu chưa ôn đủ điều kiện theo loại lỗi đang chọn, không chỉ các câu sai của lượt vừa nộp.

Sổ lỗi phân trang 20 mục và phân biệt số mục ghi lỗi với số câu khác nhau có thể làm lại. Một câu sai ở nhiều lượt gốc có thể tạo nhiều mục, nhưng chỉ xuất hiện một lần trong nhóm ôn. Các câu nghe chưa có audio hoặc bộ lựa chọn không hợp lệ sẽ không được đưa vào lượt làm lại. Bộ đếm vì vậy có thể khác nhau.

Nút **Lưu ghi chú** giữ nguyên trạng thái hiện có. **Đánh dấu đã ôn** là tự đánh dấu sau khi xem lại; **Chuyển về cần ôn** mở lại mục đã ôn. Không suy ra năng lực từ việc tự đánh dấu hoặc một lần làm đúng câu đã gặp.

## Kết quả và tiến độ

Lượt ôn sử dụng `MistakeReviewSession`, `MistakeReviewItem`, `MistakeReviewAnswer` riêng. Không sửa điểm/lựa chọn của bài gốc, không tạo `PracticeAttempt` mới, không hoàn thành task planner và không thêm câu trả lời vào tỷ lệ đúng theo kỹ năng.

Một lượt ôn đã nộp được tính là một sự kiện hoạt động riêng trên lịch 7 ngày và chuỗi ngày có học. Giao diện tách ba số: luyện bài / ôn từ / ôn câu sai. Tỷ lệ đúng kỹ năng vẫn chỉ lấy bài luyện gốc. Đây là ghi nhận hoạt động; chưa chứng minh tiến bộ hoặc mức CEFR/điểm TOEIC.

Kết quả được lưu thành snapshot ngay khi chấm: câu hỏi, lựa chọn, đáp án và giải thích. Sửa học liệu sau đó không thay nội dung kết quả cũ. Nộp lại cùng một phiên không tạo bản chấm mới và không đóng thêm các lỗi phát sinh sau này.

## Kiểm tra tính hợp lệ

- Chỉ lấy câu sai từ lượt đã nộp của chính người học, đúng kỳ thi hiện tại, đúng quan hệ giữa lượt luyện và nội dung câu hỏi; học liệu phải đang xuất bản và có trạng thái rà soát cho phép truy cập.
- Không gửi `is_correct`, giải thích, transcript hoặc kịch bản TTS trong HTML/DTO trang đang làm. Bài nghe không có audio được bỏ khỏi nhóm đủ điều kiện, thay vì đưa transcript vào đề nghe.
- Chỉ chấp nhận phương án thuộc câu hỏi đã chốt trong phiên; kiểm tra tất cả ID trước khi ghi kết quả. Câu bỏ trống được phép nộp và vẫn cần ôn.
- Có fingerprint câu hỏi/phương án. Nếu nội dung, nguồn lỗi hoặc quyền truy cập thay đổi, phiên dừng mà không chấm một phần và không đổi trạng thái các lỗi nguồn.
- Một phiên đang làm cho mỗi tài khoản/kỳ thi. Có khóa giao dịch khi chấm, nộp lặp trả snapshot. Xóa lỗi nguồn không chặn việc dọn dữ liệu: phiên đang làm mất nguồn sẽ hết hiệu lực; phiên đã nộp giữ snapshot. Câu hỏi vẫn có thể được bảo vệ khỏi xóa do lịch sử tham chiếu, tương tự bảng đáp án bài luyện gốc.
- Admin có danh sách phiên ôn theo người dùng/kỳ thi/trạng thái và số đúng/tổng câu ở chế độ chỉ đọc.

## Mã nguồn và cập nhật

Service: `learning/mistake_review.py`; các endpoint ở `learning/views.py` và `learning/urls.py`; giao diện ở ba template `mistake_notebook`, `mistake_review`, `mistake_review_result`; CSS/JS riêng trong `static`.

Migration `0010_mistake_review_sessions` thêm bảng/ràng buộc lượt ôn; `0011_mistake_review_drafts` thêm lựa chọn nháp JSON và thời điểm lưu. Sao lưu database trước khi chạy migrate trên dữ liệu đang dùng. Máy đã có dự án chạy:

```bash
python manage.py migrate
python manage.py test
node --test scripts/test_practice_draft.cjs scripts/test_tutor_workspace.cjs scripts/test_mistake_review.cjs
```

Đợt bàn giao đầu tiên vượt qua **193 test Python và 12 test JavaScript** (số liệu lịch sử trước tính năng lưu nháp). Django system check và kiểm tra migration đều đạt. Đã sao lưu trước khi áp dụng migration lên dữ liệu làm việc; kiểm tra toàn vẹn SQLite và khóa ngoại sau cập nhật. Test chấm/HTTP dùng dữ liệu kiểm thử, không gọi API AI thật.

Các agent backend, frontend, giáo viên tiếng Anh và audit cùng tham gia. Vai trò giáo viên/kiểm định ở đây là agent AI; chưa phải đánh giá của giáo viên thật. Chưa kiểm tra thị giác trên trình duyệt thật, stress test đồng thời, kiểm thử PostgreSQL hoặc pilot người học trong đợt này. Luồng này không thay đổi số lượng học liệu, mô hình truy xuất hay kết quả benchmark AI đã báo cáo ở vòng trước.


## Cập nhật lưu nháp — 20/10/2026

- Bản nháp thuộc phiên ôn của chính tài khoản, tối đa 10 câu. Lưu nháp không chấm điểm, không tạo đáp án đã nộp, không đánh dấu lỗi đã ôn và không tính thêm hoạt động học.
- Mở lại lượt ôn sẽ khôi phục lựa chọn; Sổ lỗi hiển thị số lựa chọn/thời điểm đã lưu. Trạng thái lưu phản ánh phản hồi từ máy chủ, không suy ra thành công chỉ vì đã bấm lưu.
- Lựa chọn lưu là toàn bộ trạng thái hiện tại của form. Không trộn câu bỏ trống lúc nộp với nháp cũ. Khi nộp, chỉ các lựa chọn form gửi lên được chấm.
- Bản nháp được xóa khi nộp, dừng hoặc học liệu/nguồn lỗi thay đổi làm phiên không còn hợp lệ. Phiên đã đóng trả lỗi khi cố lưu tiếp; không mở lại hoặc ghi đè kết quả đã chấm.
- Endpoint POST kiểm tra CSRF, quyền sở hữu, kỳ thi trong hồ sơ, giới hạn JSON 16 KiB và quan hệ câu hỏi/phương án. Đáp án/lời giải/transcript vẫn không có trong trang đang ôn.
- Dùng chung JavaScript lưu nháp của bài luyện chính, xếp hàng các lần lưu để lựa chọn mới nhất được gửi sau request đang chạy. Từ M1, mỗi lần lưu/nộp kiểm tra revision; request cũ bị chặn 409. Back/Forward cache yêu cầu tải lại, không tự ghi trạng thái cũ trở lại. Request treo có timeout 15 giây và giữ lựa chọn trên trang.
- Hai tab không được ghi đè âm thầm; trang xung đột giữ lựa chọn để người học xem trước khi tải lại bản đã lưu. Chưa có hợp nhất xung đột hoặc cam kết lưu khi offline/đóng ngay/JavaScript tắt. Không lưu câu trả lời nháp trong localStorage. Xem [chi tiết M1](STABILITY_M1.md).

Đã thêm kiểm thử service/HTTP và JavaScript cho lưu/khôi phục, phân quyền, CSRF, câu/phương án sai, phiên đóng, thay đổi nội dung và phục hồi lịch sử trình duyệt. Chưa thử đồng thời trên PostgreSQL hoặc kiểm tra trực quan trên Edge/mobile thật. Chạy migrate trước khi dùng bản cập nhật; môi trường production cần collectstatic/build lại image.

Kết quả kiểm tra bản lưu nháp: **221 Django tests và 34 Node tests pass**; Django system check sạch, không thiếu migration, collectstatic production thành công. Migration0011 đã áp dụng vào database làm việc sau backup; integrity_check và foreign_key_check đạt.
