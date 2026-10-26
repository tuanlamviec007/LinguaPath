# LinguaPath — tạm giữ thẻ và sửa lỗi trip M9

Cập nhật **25/10/2026**. Hoàn thành xử lý lỗi dữ liệu C03 theo phạm vi đã biết và thêm khả năng giữ riêng flashcard. **Cần migration0022**. Không thêm học liệu mới, không tự duyệt chuyên môn hoặc mở lại nguồn vừa sửa.

## Nâng cấp bản cài hiện có

Giữ database và cấu hình của máy đang chạy, backup trước khi cập nhật. Không seed lại để sửa lỗi cũ.

```bash
python manage.py migrate
python manage.py repair_starter_trip --quarantine-card
# Xem kết quả khớp/ảnh hưởng trước rồi áp dụng đúng sửa lỗi đã biết:
python manage.py repair_starter_trip --quarantine-card --apply
python manage.py check_schema
python manage.py check_weak_word_outcomes
```

Lệnh chỉ khớp đầy đủ nguồn lỗi cũ của trip, không dựa vào ID cố định. Không khớp thì không thay đổi; không ghi đè bản dịch/nguồn đã chỉnh sửa. Các ID dưới đây là kết quả của database dự án hiện tại, không dùng như điều kiện áp dụng trên máy khác. Bản cài mới từ CSV đã sửa sẽ không có bản ghi cũ để áp dụng.

Chế độ quarantine chỉ áp dụng cho parent draft/language_checked, không giữ nhãn teacher_approved khi sửa nguồn. Nếu bản sao lời giải trong bộ đã biết khác bản cũ, bị trùng hoặc đã được chuyên môn duyệt, lệnh dừng nguyên tử để người biên tập đối chiếu. Chế độ `--apply` cũ không kèm quarantine vẫn đưa cả bộ từ vựng về nháp như trước.

## Đã sửa trong database dự án

- Backup riêng trước thay đổi rồi áp dụng `0022_flashcard_availability`.
- Thẻ **#778**: ghép lại bản dịch ví dụ đầy đủ và sửa topic thành Travel; `is_available=false`, có ghi chú chờ người duyệt.
- Parent **#3** không đổi metadata/xuất bản; vẫn giữ đủ1.000 thẻ,999 thẻ có thể dùng. Không ẩn cả bộ vì một thẻ.
- Phát hiện câu **#706** trong parent45 sao chép bản dịch bị cắt. Đã sửa lời giải; parent **#45** gồm20 câu được chuyển về nháp/chưa xuất bản để rà lại, không tự xuất bản sau sửa.
- Không xóa thẻ/câu hỏi hoặc thay snapshot, kết quả, bookmark, lịch ôn, XP hay tài khoản. Các trường gốc chỉ đổi ở card778, question706, parent45 và thêm migration record; các dòng gốc khác được đối chiếu với backup và giữ nguyên.

`trip_repair_m9.json` ghi before/after và hash backup, không chứa database hoặc credential. `content_coverage_m9.json`:429 parent,3.056 thẻ,5.138 câu;428 parent/3.055 thẻ/5.118 câu đang khả dụng theo quy tắc hiện tại;1 thẻ tạm giữ,0 teacher_approved. Đây là kiểm kê, không phải chứng nhận chất lượng toàn kho.

## Thẻ đang tạm giữ hoạt động thế nào?

Manager mặc định vẫn đọc đủ dữ liệu cho admin/import/seed và kiểm kê. Luồng học dùng điều kiện riêng: thẻ available, parent đã xuất bản với trạng thái cho phép và đúng kỳ thi. Thẻ held không vào flashcard, quiz mới/retry, sổ từ hiện hành, hàng đợi từ yếu, bài xếp mức, gợi ý/truy xuất Tutor hoặc thống kê ôn hiện hành.

Quiz đang mở được kiểm tra lại khi đọc/nộp; thẻ vừa bị giữ làm phiên không còn đủ điều kiện nộp. Bài xếp mức lưu ID/phiên bản của thẻ đích và cả phương án nhiễu, kiểm tra lại dưới khóa trước chấm. Phiên cũ thiếu nguồn hoặc có thẻ vừa giữ/sửa hết hiệu lực, không ghi đè kết quả đã có. SRS kiểm tra lại dưới thứ tự khóa User → Content → Card trước ghi. PostgreSQL concurrency vẫn cần chạy thực tế.

Nhiệm vụ từ vựng chưa hoàn thành không còn thẻ khả dụng ở mức đã chọn được ẩn, không tự thêm nhiệm vụ thay thế. Nhiệm vụ đã hoàn thành, hoạt động/XP, bookmark, review và quiz đã nộp vẫn còn. Lịch sử Tutor giữ nguyên câu trả lời, tắt liên kết nguồn held với trạng thái withdrawn. Không hứa xóa dữ liệu nguồn khỏi snapshot cũ của chính người học.

Trong admin Flashcard có bộ lọc và trường **Cho phép học thẻ**. Chỉ tắt availability/ghi chú có thể giữ riêng thẻ mà không thay trạng thái cả parent. Sửa nội dung hoặc bật lại thẻ vẫn đưa parent về nháp theo quy tắc rà soát; giao diện có giải thích ảnh hưởng. Không dùng checkbox để tự gán teacher_approved. Seed không tự bật lại thẻ held; bộ sinh starter giữ ranh giới nhóm20 thẻ, bỏ qua held khi tạo câu mới để không dịch chuyển các bộ khác. Bản sao câu đã có là đối tượng riêng và cần xử lý cụ thể như #706.

## Phiếu người duyệt v2

Schema mới `linguapath-content-review-v2` giữ availability/note trong bằng chứng và hash, ưu tiên thẻ held trước trong mẫu, sau đó order/ID. Đề và lựa chọn câu hỏi vẫn giữ thứ tự riêng. Editor chỉ đọc trạng thái này, không mở lại thẻ từ phiếu. Mẫu luôn `approval_allowed=false`.

`trip_review_sample_m9.json` có20 thẻ (gồm778 ở đầu) và toàn bộ20 câu của parent45 (gồm706), nhận xét người duyệt để trống. Mẫu20 thẻ không chứng nhận cả1.000 thẻ của parent3. Phiếu v1 cũ vẫn được giữ như hồ sơ lịch sử nhưng không tự mở tiếp trên schema mới; xuất v2 và người duyệt đối chiếu lại nguồn/nhận xét. Không chuyển nhận xét cũ thành phê duyệt mới.

Đã chạy lại retrieval/router ngoại tuyến theo kho khả dụng mới, ghi `retrieval_evaluation_m9.json` và `tutor_router_evaluation_m9.json`. Kho khả dụng3.055 thẻ; retrieval v2 Recall@3 vẫn57/80=0,7125, abstention âm5/16; router16/16 ca đã biết khớp nguồn. Không điều chỉnh scorer hoặc biến bộ hồi quy cũ thành holdout; chưa đánh giá model thật.

## Kiểm chứng và phần còn mở

**761 Django tests:753 đạt,8 PostgreSQL-only skip;104/104 JavaScript tests đạt.** Thêm30 tests Django và1 JS cho availability, learner flows, placement nguồn/version, SRS/planner, seed grouping, repair nguyên tử, admin và phiếu v2. Regression số query recall vẫn đạt1 query cho index mới; lookup dùng index được truyền sẵn vẫn kiểm tra lại availability. System/schema/projection/local-release checks, migration drift và collectstatic đạt. Đã thử editor v2 bằng template thật render từ DB memory: nhãn tạm giữ/ghi chú hiển thị, desktop và iframe375px không tràn document; các ô editor có label. Đây là browser QA tĩnh, backend dùng Django Client, chưa phải browser–Django live E2E hoặc thiết bị thật.

C03 đã xử lý dữ liệu lỗi đã xác định và ngăn nguồn đó vào bài mới; việc duyệt/mở lại thuộc C01/C05, chưa hoàn thành. Các mục model/holdout/calibration và PostgreSQL/Docker/Cloudflare/CI thực vẫn giữ mở. M9 không phải nghiệm thu toàn bộ audit.
