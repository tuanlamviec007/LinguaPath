# Kho từ vựng 3.000+ và bài luyện — 21/10/2026

## Kết quả đã nạp

| Nội dung | Số lượng |
|---|---:|
| Thẻ từ toàn dự án | 3.016 |
| Từ/cụm từ khác nhau sau chuẩn hóa chữ hoa và khoảng trắng | 3.012 |
| Thẻ bổ sung trong đợt này | 2.000 |
| Bài tập bổ sung | 4.000 câu |
| Bộ luyện bổ sung | 228 bộ: 114 chọn nghĩa, 114 điền từ |
| Bộ thẻ bổ sung | 114 bộ |
| Tổng số câu hỏi toàn dự án | 5.058 |

Kho cũ có 1.016 thẻ và 1.058 câu; đợt này thêm 2.000 thẻ, 2.000 câu chọn nghĩa trong ngữ cảnh và 2.000 câu điền từ. Không thêm bài Reading/Listening dài, audio hoặc đề thi thử đủ cấu trúc trong lần này. Các bộ mới có tối đa 20 câu, chia theo mức và sáu nhóm lớn; chia cân đối để hạn chế bộ cuối quá ít câu. Một số nhóm ít từ vẫn có thể có 4 câu.

| CEFR tham khảo | Thẻ hiện có |
|---|---:|
| A1 | 359 |
| A2 | 678 |
| B1 | 877 |
| B2 | 830 |
| C1 | 272 |

Đây là số thẻ, không phải số họ từ, số nghĩa đã được kiểm định hoặc lượng từ bảo đảm để đạt một mức điểm. Bốn mục trùng dạng viết giữa các bộ cũ giải thích chênh lệch giữa số thẻ và số từ/cụm từ khác nhau.

## Quan hệ với Cambridge

Cambridge English có danh sách hướng dẫn từ vựng A2 Key/B1 Preliminary và hệ thống tham chiếu English Profile. Trong lần làm này chưa xác minh một danh sách Cambridge chính thức tên “Cambridge 3000” bao phủ A1–C1, hoặc quyền sao chép nguyên kho định nghĩa/ví dụ/audio để công bố trên web.

Bộ bổ sung được các agent AI tự biên soạn nghĩa tiếng Việt, câu tiếng Anh, bản dịch và phương án nhiễu. Không lấy nguyên định nghĩa, ví dụ hay audio Cambridge. Nút **Tra Cambridge** trên thẻ mở trang từ điển tiếng Anh chính thức; người học nhập từ cần tra. Nút này không chứng minh Cambridge xác nhận dữ liệu trên thẻ hoặc nhãn CEFR của từng nghĩa.

Các mức A1–C1 đều tạm thời, chưa đối chiếu và được người có chuyên môn phê duyệt từng mục; không quy đổi thành điểm TOEIC/IELTS hoặc chứng chỉ. Từ/cụm từ bao gồm nhiều nhóm đời sống/học tập/công việc, không phải danh sách xếp hạng 3.000 từ có tần suất cao nhất.

Nguồn tham khảo đã mở trong phiên làm việc:

- https://www.cambridgeenglish.org/exams-and-tests/qualifications/key/preparation/
- https://www.cambridgeenglish.org/Images/506886-a2-key-2020-vocabulary-list.pdf
- https://www.cambridgeenglish.org/exams-and-tests/qualifications/preliminary/preparation/
- https://dictionary.cambridge.org/dictionary/english/
- https://www.cambridge.org/rights-and-permissions

## Cách sử dụng trên website

- Mở Từ vựng, chọn thẻ đến hạn hoặc toàn bộ kho; tìm theo từ/nghĩa/ví dụ và lọc CEFR/chủ đề. Thẻ giữ lật hai mặt, ví dụ/bản dịch, phát âm bằng giọng thiết bị và lịch ôn hiện có.
- Mở Thư viện bài luyện, chọn Từ vựng và dạng **Chọn nghĩa trong câu** hoặc **Điền từ vào câu**. Bộ lọc giữ dạng bài khi chuyển trang.
- Mỗi câu có bốn phương án và một đáp án lưu trong hệ thống. Sau khi nộp mới xem câu hoàn chỉnh, nghĩa và bản dịch. Các phương án nhiễu có mức khó khác nhau, chưa được hiệu chuẩn với người học.
- Bộ mới hiện gắn mục tiêu TOEIC theo MVP đang có; chưa tạo chương trình IELTS hoàn chỉnh.

## Cài đặt/cập nhật

Máy mới chạy các lệnh seed cũ trước, rồi thêm catalog:

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py seed_starter_content
python manage.py seed_advanced_content
python manage.py seed_vocabulary_3000 --dry-run
python manage.py seed_vocabulary_3000 --publish-provisional
```

Máy đã có bộ cũ chỉ cần hai lệnh cuối. **Không chạy lại seed cũ trên học liệu giáo viên đã sửa**: các lệnh cũ có cơ chế cập nhật nội dung. Riêng seed mới chỉ tạo bộ chưa có và giữ nguyên bộ đã tồn tại, gồm chỉnh sửa của giáo viên và lịch sử người học. Chạy từng tiến trình seed một lần, không chạy đồng thời nhiều tiến trình vì tên bộ chưa có ràng buộc duy nhất trong database.

Không có flag `--publish-provisional` thì bộ mới vào nháp, chưa hiển thị cho người học. Flag cho phép dùng bản AI rà soát sơ bộ trong demo; không biến thành teacher-approved. Nếu đã tạo nháp trước đó, chạy lại với flag cũng không ghi đè/đổi trạng thái bộ cũ; duyệt và xuất bản trong admin. Nguồn, quyền sử dụng và ghi chú rà soát được giữ trên từng bộ/thẻ.

Trước khi nạp dữ liệu làm việc đã tạo backup SQLite. Lệnh nhập kiểm tra cấu trúc toàn catalog trước khi ghi; nếu trùng từ thuộc bộ ngoài catalog thì dừng thay vì xóa/ghi đè dữ liệu đó. Sau nạp đã kiểm tra toàn vẹn database, khóa ngoại và bốn lựa chọn/một đáp án cho 4.000 câu mới. Chạy lặp không tạo thêm bộ/câu/thẻ.

## Dữ liệu và kiểm định

Sáu CSV tác giả chứa 2.160 mục ứng viên gốc. `selected_2000.csv` là tập 2.000 mục thực sự được seed; các CSV nguồn không tự được xuất bản. Script `scripts/build_vocabulary_catalog.py` loại trùng và tái tạo tập chọn có tính xác định. `catalog_report.json` ghi phân bố và loại trùng; `installed_counts.json` là snapshot số lượng sau nạp.

Các agent đã tự kiểm tra và rà soát chéo; đã sửa các lỗi cụ thể như charcoal/than chì, nghĩa của laser, bản dịch guest room, cùng một số câu có nhiều đáp án hợp ngữ cảnh. Kiểm tra tự động xác nhận cột bắt buộc, từ trùng, đáp án xuất hiện một lần trong ví dụ, bốn lựa chọn khác nhau và nhãn CEFR hợp lệ về cấu trúc. Những kiểm tra này không chứng minh mọi nghĩa, CEFR và phương án nhiễu đều đúng về ngôn ngữ.

Cần giáo viên kiểm tra từng lô, hiệu chỉnh distractor và thử với người học trước khi quảng bá như kho học liệu đã kiểm định. Chưa có kiểm thử trực quan Edge/mobile hoặc deployment Cloudflare được xác nhận trong đợt này.

Kết quả kiểm tra: **231 Django tests và 34 Node tests pass**; Django system check sạch. Không cần migration mới cho đợt dữ liệu này. Tăng kho từ chưa được đo lại Recall/MRR của trợ lý; không coi đây là bằng chứng trợ lý trả lời tốt hơn.
