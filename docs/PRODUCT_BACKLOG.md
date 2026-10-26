# Hướng phát triển LinguaPath do các agent đề xuất

## 23/10/2026 — Tự nhớ và gõ từ

Đã triển khai [quiz gõ từ tiếng Anh](TYPED_RECALL.md), nối cùng nháp, retry, nguồn cá nhân, hàng từ cần ôn và lịch sử hiện có. Bốn agent phụ trách giao diện, JavaScript, kiểm thử và audit; root triển khai backend/tích hợp. Audit phát hiện và xử lý prompt chứa đáp án, JSON legacy không hợp lệ và Enter khi đang ghép chữ. Cách chấm là đối sánh từ gốc có chuẩn hóa, chưa chấm ngữ nghĩa bằng AI. Cần theo dõi phản hồi về định nghĩa nhiều nghĩa và kiểm tra thiết bị thật.

## 23/10/2026 — Lịch sử quiz đầy đủ

Đã thêm [lịch sử quiz có bộ lọc và phân trang](QUIZ_HISTORY.md), giúp tìm lại kết quả ngoài vài lượt gần nhất. Agent giao diện và agent kiểm thử cùng tham gia; root xử lý dữ liệu, tích hợp và xác minh trực quan. Thống kê chỉ gộp quiz mới theo tổng câu; lượt ôn được đếm riêng. Dùng phạm vi tài khoản/mục tiêu thi/ngày nộp thật cho cả lịch sử và danh sách gần đây. Không có thay đổi schema, thưởng XP hoặc học liệu.

## 23/10/2026 — Từ cần ôn

Đã bổ sung [hàng ôn từ từng sai qua quiz](WEAK_WORDS.md), nối tiếp Sổ từ cá nhân. Bốn agent phụ trách backend, giao diện, kiểm thử và audit; root tích hợp dashboard/tiến độ, xác minh giao diện và đóng gói. Danh sách tự cập nhật theo câu trả lời gần nhất; luyện riêng từ một câu, không cộng XP và không trộn kết quả với quiz mới. Không thay thế lịch SRS hoặc kết luận thành thạo sau một lần đúng. Phần cần theo dõi: chi phí đọc lịch sử dài và phản hồi người học thật.

Đợt này dùng agent nghiên cứu sản phẩm, giáo viên tiếng Anh, kỹ sư kiến trúc, backend, frontend và AI. Các vai trò giáo viên/giảng viên ở đây là vai trò của agent AI, không phải xác nhận bởi giảng viên thật.

## Quyết định đã triển khai

| Ý tưởng | Vấn đề của sinh viên | Quyết định và kết quả |
|---|---|---|
| Tiếp tục bài còn dang dở | Bị ngắt giữa giờ học/đi làm, mất lựa chọn hoặc tạo nhiều lượt làm trùng | Ưu tiên đầu tiên. Lưu nháp, khôi phục lựa chọn, một lượt đang làm cho mỗi bài/tài khoản, CTA tiếp tục trên dashboard. |
| Tiến độ dẫn tới hành động | Tỷ lệ đúng chung không cho biết nên luyện kỹ năng nào | Thêm bảng 30 ngày theo Reading/Listening/Từ vựng, số đúng/tổng câu, liên kết đến thư viện đã lọc. Khi ít hơn 5 câu thì chưa hiện phần trăm. |
| Nhịp học bền vững | Khó nhận ra các ngày đã học gần đây | Thêm lịch hoạt động 7 ngày và chuỗi ngày dựa trên lượt luyện đã nộp/lượt ôn từ; không suy ra số phút học từ lượt truy cập. |
| Nhiệm vụ tiếp theo rõ ràng | CTA có thể mở lại task đã xong; lý do gợi ý thiếu ngữ cảnh | CTA ưu tiên bài đang dở, sau đó task chưa hoàn thành, cuối cùng mới mời học thêm tùy chọn. Giữ lý do lựa chọn task hiện có. |

## Vai trò và đầu ra

- Nghiên cứu sản phẩm: xếp hạng ba increment theo nhu cầu sinh viên; triển khai service thống kê hoạt động và kiểm thử riêng tư/múi giờ.
- Giáo viên tiếng Anh: đề xuất giảm gián đoạn học, tách hoạt động khỏi năng lực, giữ phạm vi TOEIC nền tảng và nhãn trình độ tham khảo.
- Kiến trúc: đề xuất tách bản nháp khỏi dữ liệu chấm điểm, kiểm tra quyền sở hữu, khóa nội dung và migration; phát hiện lỗi draft cản admin xóa nội dung để sửa.
- Backend: service tạo/tiếp tục/lưu nháp, fingerprint câu hỏi, kiểm tra ID/quan hệ lựa chọn, khóa giao dịch và kiểm thử.
- Frontend: giao diện tiếp tục bài, trạng thái lưu, hàng đợi autosave, khôi phục radio, cảnh báo chưa lưu và tổng kết hoạt động; sáu test JavaScript mô phỏng.
- AI: đề xuất hai bước nâng chất lượng truy xuất và đánh giá trợ lý dưới đây; chưa thay đổi mô hình hoặc gọi API trong đợt này.

## Backlog được ưu tiên tiếp theo

| Ưu tiên | Đề xuất | Phạm vi nhỏ nhất | Bằng chứng cần có trước khi kết luận hiệu quả |
|---|---|---|---|
| Đã làm bản đầu — 20/10 | Truy xuất tiếng Việt có dấu/không dấu | Chuẩn hóa truy vấn và văn bản cho fallback; giữ nguyên văn nguồn khi hiển thị; bảo toàn giới hạn nội dung/người dùng hiện tại | Bộ khoảng 80–120 truy vấn có nhãn nguồn; tách dev/test cố định; so sánh Recall@3, MRR@3 và khả năng từ chối truy vấn không phù hợp. |
| 2 | Đánh giá chất lượng giải thích | Khoảng 40–60 ca gồm giải thích đáp án, nhiễu, từ vựng, thiếu nguồn và chỉ dẫn gây nhiễu; rubric bám nguồn/đúng/đủ | Chấm độc lập, ghi nhận độ chính xác lời giải, tỷ lệ trả lời có căn cứ, độ đúng của nguồn và độ trễ. Không gọi hệ thống chống hallucination chỉ từ lời nhắc. |
| 3 | Duyệt học liệu và pilot | Chia nhỏ 848 mục AI hỗ trợ thành từng lô; người có chuyên môn kiểm tra sense, ví dụ, CEFR và distractor; thử luồng học với sinh viên | Ghi người duyệt thật, thay đổi từng mục, số lỗi/độ đồng thuận và phản hồi người học. Không tự chuyển thành teacher-approved bằng agent. |

Một lịch SRS 7 ngày mới trên dashboard chưa được chọn vì trang Tiến độ đã có lịch này. Bổ sung tính năng tiếp theo nên dựa trên kết quả sử dụng, tránh tạo thêm màn hình lặp chức năng.

## Kết quả vòng trợ lý 20/10

Đã tích hợp luật chuẩn hóa, gợi ý câu hỏi và thẻ nguồn; agent AI, frontend, biên tập benchmark và kiến trúc cùng tham gia. [Báo cáo thực nghiệm](AI_RETRIEVAL.md) đo 96 truy vấn: tìm đúng từ tường minh tốt hơn, nhưng từ chối ngoài phạm vi và diễn đạt vòng còn yếu. Ưu tiên tiếp theo là bộ nhãn người thật, phân biệt nghĩa và giảm trả nguồn không phù hợp; cần tập test mới trước vòng điều chỉnh tiếp theo. Không tự đánh dấu nội dung là giảng viên đã duyệt.


## Vòng hai — tra cứu chủ động và làm rõ nghĩa

Đã bổ sung lựa chọn tra cứu/AI (mặc định không gọi dịch vụ ngoài), xếp hạng theo ngữ cảnh, gộp thẻ cùng nghĩa và hỏi lại các nghĩa đồng điểm. Giao diện hiện nghĩa ở thẻ nguồn và chữ hướng dẫn dễ đọc hơn. [Bộ v2 độc lập](TUTOR_V2.md) vẫn cho thấy chất lượng truy xuất chưa đạt: ngoài phạm vi tốt hơn một phần, Recall giảm. Không đổi thuật toán theo test sau khi mở kết quả.

Ưu tiên tiếp theo: phân biệt câu hỏi chung có dẫn nhập với yêu cầu từ vựng; đánh giá theo nghĩa bằng nhãn người thật; nâng truy vấn nghĩa tiếng Việt chưa có từ đích, trước khi thêm tính năng AI khác. Phần phát hành cần kiểm tra trình duyệt, pilot và rà soát học liệu. Chưa mở công khai hoặc gọi API thật trong vòng này.


## Vòng ba — học lại từ câu sai

Đã triển khai [lượt ôn câu sai](MISTAKE_REVIEW.md): tối đa 10 câu khác nhau, nhóm riêng không lộ lời giải khi làm, snapshot kết quả sau nộp, trạng thái sai/bỏ trống còn pending, câu đúng chuyển đã ôn. Tách khỏi điểm bài gốc/planner, ghi nhận riêng trong hoạt động/streak. Sổ lỗi có phân trang, lịch sử và ba hành động ghi chú/đã ôn/mở lại rõ ràng. Backend, frontend, giáo viên và audit đều tham gia.

Đã bổ sung lưu nháp/khôi phục lựa chọn trong lượt ôn. Phần còn mở: biến thể câu hỏi và lịch ôn có khoảng cách để đánh giá khả năng vận dụng; kiểm tra trình duyệt/pilot người học. Không coi việc làm đúng một câu đã gặp là thành thạo. Các hạn chế truy xuất AI của vòng hai vẫn được giữ nguyên.


## Vòng giao diện — 20/10

Đã làm mới [giao diện khách, người học và admin](UI_REFRESH.md): điều hướng desktop/mobile, trang chủ có thẻ mẫu, tổng quan ưu tiên nhiệm vụ, form đăng nhập/đăng ký và chữ/vùng bấm rõ hơn. Giữ dữ liệu thật và phạm vi TOEIC của MVP. Cần kiểm tra trực quan desktop/mobile trên máy thật; lần mở trình duyệt kiểm tra trong môi trường hiện tại bị timeout, chưa có ảnh xác nhận.


## Vòng trải nghiệm học — 20/10

Đã thêm [không gian flashcard và luyện nghe](LEARNING_WORKSPACE.md): tab đến hạn/thư viện, player có tốc độ và tua lại, nghe lại ở kết quả, xử lý lỗi/focus và nhóm câu theo đoạn nghe. Các agent frontend, backend, AI, giáo viên, thiết kế và audit tham gia. Chưa thêm kho nội dung hoặc tuyên bố cải thiện điểm số; cần kiểm thử thiết bị thật và pilot trước khi quảng bá rộng.


## Vòng tiếp tục lượt ôn — 20/10

Đã hoàn thiện [lưu nháp lượt ôn câu sai](MISTAKE_REVIEW.md): khôi phục lựa chọn theo tài khoản, trạng thái lưu/nút lưu thủ công và số lựa chọn lưu trên Sổ lỗi. Thêm migration0011, kiểm tra quyền và snapshot trước khi lưu, dọn nháp khi phiên kết thúc; không thay đổi điểm bài gốc hoặc khối lượng học liệu. Sửa phục hồi Back/Forward cache và cảnh báo khi hủy autosave để nộp bài. Cần pilot/kiểm tra thiết bị thật và xử lý xung đột nhiều tab ở vòng sau.


## Vòng kho từ 3.000+ — 21/10

Đã thêm [2.000 mục từ gốc và 4.000 câu luyện từ vựng](VOCABULARY_3000.md), nâng demo lên 3.016 thẻ/5.058 câu. Sáu nhóm biên soạn và audit AI tham gia; có bộ lọc dạng bài, nhập create-only giữ chỉnh sửa và liên kết tra từ Cambridge. Cần giáo viên duyệt từng lô và hiệu chuẩn độ khó; không gọi đây là bộ Cambridge chính thức hoặc chương trình đủ để bảo đảm điểm thi.


## 21/10/2026 — TOEIC AI Tutor và Workers AI

Đã triển khai 4 thao tác nhanh, lịch sử riêng tối đa 50 lượt (migration0012), 8 ghi chú ngữ pháp/chiến thuật, gợi ý bộ luyện theo mức, tiến độ và nhiệm vụ từ dữ liệu thật. Có Worker AI binding, cầu nối nội bộ có secret, hạn mức tài khoản và DO toàn hệ thống. Admin có thể yêu cầu Workers AI soạn 3 câu Part 5 vào nháp; kiểm tra cấu trúc, yêu cầu duyệt chuyên môn trước xuất bản. 248 Django + 42 Node tests đạt, Worker dry-run đạt. Chi tiết và các phần chưa làm: [CLOUDFLARE_AI_TUTOR.md](CLOUDFLARE_AI_TUTOR.md). Chưa có xác thực Cloudflare/Docker/PostgreSQL production, chưa gọi model thật hoặc công bố URL.
