# LinguaPath — website luyện TOEIC có lộ trình cá nhân

**Triển khai Django đầy đủ:** đã bổ sung [cấu hình Render Free + Neon](docs/DEPLOY_RENDER_NEON.md),
`render.yaml`, build có dependency hash và nhập học liệu một lần khi database trống.
Startup chỉ kiểm tra release rồi phục vụ, không tự seed mỗi lần khởi động.
Chưa được coi là deploy thành công cho đến khi có URL và kiểm chứng trên dịch vụ thật.

**26/10/2026 — M12:** thêm [tìm từ theo mô tả](docs/STABILITY_M12.md) trong Tutor: tối đa3 ứng viên theo từ ngữ nguồn, chọn từ trước khi giải thích, không dùng lượt AI và có nút chọn khi tắt JavaScript. Luồng mặc định M11 giữ nguyên; khả năng diễn đạt lại còn thấp (2/20 ca ứng viên trên regression cũ), chưa nghiệm thu semantic search. Không có migration mới sau0023.

**26/10/2026 — M11:** cải thiện [truy xuất Tutor và đo theo nghĩa](docs/STABILITY_M11.md). Nhận yêu cầu tra rõ hơn, giảm trùng từ tình cờ, hỏi lại khi ngữ cảnh nghĩa yếu; thêm fixture/metric nghĩa với ghi báo cáo an toàn. Trên regression v2 đã biết:61/80 mục từ và16/16 ca âm, nhưng paraphrase chỉ1/20; chưa phải nghiệm thu độc lập. Không có migration mới sau0023.

**25/10/2026 — M10:** thêm [gõ từ đến lịch ôn](docs/STABILITY_M10.md): thẻ đến hạn, cách lần tự đánh giá ít nhất24 giờ; ghi kết quả riêng, không gộp retry và không đổi lịch SRS/CEFR. Nhãn tiến độ/planner phân biệt tự đánh giá với thành thạo. Backup rồi migrate đến **0023**, không seed/backfill bằng chứng cũ. C06 vẫn chờ pilot thực tế.

**25/10/2026 — M9:** [tạm giữ riêng thẻ và sửa dữ liệu trip](docs/STABILITY_M9.md). Đã sửa bản dịch lệch cột và lời giải sao chép, cách ly nguồn chờ duyệt; lịch sử học giữ nguyên. Cần backup rồi migrate đến **0022**, dùng lệnh sửa có kiểm soát theo tài liệu nếu máy còn bản ghi cũ; không seed lại. Phiếu người duyệt nâng lên v2.

**25/10/2026 — M8:** thêm [gate khởi động và smoke container CI](docs/STABILITY_M8.md). Production kiểm tra cấu hình/schema/projection trước Gunicorn; CI từ chối fallback SQLite và có kiểm tra CSRF/login/session sau restart image. Test hợp đồng Django đã có; Docker/PostgreSQL runtime vẫn chờ runner thật. Không có migration mới.

**25/10/2026 — M7:** thêm [đánh giá câu trả lời Tutor](docs/STABILITY_M7.md), snapshot ngữ cảnh thật trong pipeline và phiếu chấm gắn phiên bản. Đã chạy16 ca hồi quy ngoại tuyến; chưa gọi/chấm model thật hoặc xác nhận holdout độc lập. Live có cap riêng cho lần chạy và vẫn dùng quota hiện hành; không có migration mới.

**25/10/2026 — M6:** thêm [biểu mẫu điền và đối chiếu phiếu duyệt](docs/STABILITY_M6.md): đọc nguồn/đáp án trong admin, ghi checklist/nhận xét từng mục, tải bản nháp và mở lại sau kiểm tra phiên bản. Không tự ghi nhận xét vào database hoặc chuyển trạng thái phê duyệt; không có migration mới.

**25/10/2026 — M5:** thêm [workspace chuẩn bị duyệt pilot](docs/STABILITY_M5.md) trong admin, báo cáo độ phủ và phiếu mẫu20 thẻ/24 câu cho người có chuyên môn. Không tự phê duyệt/xuất bản và không có migration mới nếu đã cập nhật M4. Xem [blueprint pilot](docs/PILOT_BLUEPRINT.md); kiểm kê không thay đánh giá ngôn ngữ hoặc hiệu chuẩn.

Cập nhật tiếp **24/10/2026 — M4**: [từ yếu, tiến độ và vận hành](docs/STABILITY_M4.md). Danh sách từ yếu dùng projection, không tải snapshot lịch sử khi đọc; tiến độ tách cách luyện/mức/nguồn, có log an toàn, dependency lock/hash Linux và trang tải/xóa dữ liệu riêng có xác thực lại. Backup rồi migrate đến **0021**, chạy backfill và `check_weak_word_outcomes` theo tài liệu trước khi chuyển traffic. [Trạng thái từng mục audit](docs/AUDIT_STATUS_2026-10-24.md) ghi rõ phần còn mở; [workflow CloudShop có thể áp dụng](docs/CLOUDSHOP_WORKFLOW_APPLICABILITY.md) được đánh giá riêng, chưa kết nối dịch vụ Big Data.

Cập nhật **24/10/2026**: [AI Tutor: ngữ cảnh, lịch sử nguồn và quota chung](docs/STABILITY_M3.md). Giữ đáp án/lời giải trước khi gửi AI; cảnh báo nguồn lịch sử đã đổi hoặc không còn truy cập được; định tuyến nhiều chủ điểm và giới hạn request dùng chung cho cả hai provider. Cần backup rồi chạy `python manage.py migrate` đến **0020**; không seed lại. Kết quả kiểm tra AI hiện là ngoại tuyến, chưa gọi model hoặc triển khai production.

Mới nhất: [Quiz gõ từ tiếng Anh](docs/TYPED_RECALL.md). Xem nghĩa tiếng Việt và gợi ý, tự nhập từ/cụm từ đã học; lưu nháp, tiếp tục, chấm đáp án gốc và ôn lại từ sai. Dùng được với thư viện, sổ cá nhân và từ cần ôn; lịch sử có bộ lọc cách luyện. Cập nhật cần `python manage.py migrate` (migration0017), không cần seed lại.

Mới nhất: [Lịch sử quiz đầy đủ](docs/QUIZ_HISTORY.md). Xem kết quả cũ, lọc 7/30 ngày hoặc toàn bộ thời gian, nguồn từ, lượt mới/luyện lại, mức và chủ đề đã chọn. Phân trang 20 lượt, thống kê tách quiz mới với lượt ôn; có lối vào từ khu quiz, tiến độ và kết quả. Không cần migration mới.

Giao diện mới: [sáng và thoáng hơn](docs/BRIGHT_UI.md), nền trắng, dashboard/flashcard mint nhạt, quiz tím lavender và sổ ôn màu đào. Cập nhật mã nguồn rồi tải lại trang; đợt chỉnh giao diện này không có migration mới.

Mới nhất: [Từ cần ôn](docs/WEAK_WORDS.md). Tự tổng hợp từ trả lời sai qua các quiz, tìm/lọc và luyện riêng từ một câu. Lần trả lời đúng tiếp theo đưa từ ra khỏi danh sách; nếu lại sai, từ xuất hiện lại. Dashboard và tiến độ có số từ đang cần ôn. Lượt ôn không cộng XP, vẫn tính ngày học và giữ suất thưởng quiz mới. Cập nhật cần `python manage.py migrate` (migration0016); không cần seed lại.

[Sổ từ cá nhân](docs/PERSONAL_WORDS.md): lưu/bỏ từ từ flashcard hoặc kết quả quiz, tìm/lọc bộ sưu tập riêng theo trình độ/chủ đề và chơi quiz chỉ từ các từ đã lưu. Dashboard có lối vào sổ; lưu từ không tự cộng XP hoặc thay đổi lịch ôn. Cập nhật cần `python manage.py migrate` (migration0015); không cần chạy lại seed.

Mới nhất: [lưu nháp quiz và ôn riêng từ sai](docs/QUIZ_RESUME_REVIEW.md). Quiz tự lưu theo tài khoản, mở lại ở câu chưa trả lời đầu tiên, có nút lưu thủ công và xử lý xung đột giữa hai tab. Trang kết quả tạo lượt ôn riêng các từ sai; lượt ôn không cộng thêm XP. Dashboard có tiếp tục quiz, trang tiến độ tách kết quả làm đầu với lượt ôn lại. Cập nhật cần chạy `python manage.py migrate` (migration0014).

## Nâng cấp 22/10/2026 — Quiz & gamification

Dashboard có linh vật minh họa, XP, cấp độ trò chơi, chuỗi ngày học, nhiệm vụ ngày và 6 huy hiệu. **Quiz thử thách** lấy từ vựng đã xuất bản theo mục tiêu học, lọc CEFR/chủ đề và chọn 5/10/15 câu; đáp án được chấm phía máy chủ. Có tiếp tục/dừng lượt đang dở, xem kết quả và ôn lại từng từ. Kho học liệu thêm 40 cụm từ Workplace và 80 câu hỏi có ví dụ song ngữ.

Cập nhật bản cài hiện có:

```bash
python manage.py migrate
python manage.py seed_toeic_workplace --publish-provisional
python manage.py runserver
```

Giữ `db.sqlite3`, `.env` và môi trường Python trên máy khi chép bản cập nhật. Gói mã nguồn không kèm database hoặc thông tin đăng nhập. Seed giữ nguyên chỉnh sửa của giáo viên; bỏ cờ `--publish-provisional` để nhập nháp. Nội dung/CEFR mới vẫn là tham khảo, chưa được giáo viên duyệt toàn bộ. Xem [chi tiết nâng cấp](docs/UPGRADE_2026-10-22.md).

Đồ án xây dựng website học tiếng Anh, phiên bản MVP hiện tập trung vào TOEIC: tài khoản, flashcard A1–C1 có nhắc lại theo lịch, bài Reading và Listening tự biên soạn, lưu kết quả, kế hoạch học theo dữ liệu luyện tập và trợ lý truy xuất lời giải.

Nội dung mẫu được viết mới cho mục đích minh họa; không phải đề thi chính thức của ETS. Website không dự đoán hoặc cấp điểm TOEIC chính thức. Listening mẫu dùng giọng đọc tiếng Anh có sẵn trong trình duyệt từ kịch bản tự biên soạn, không phải bản ghi âm người bản ngữ. IELTS, Writing/Speaking và đề thi thử đầy đủ chưa thuộc bản demo.

Giao diện mới: [trang khách, khu học tập và quản trị](docs/UI_REFRESH.md), với thanh điều hướng riêng, thẻ mẫu lật được, tổng quan tập trung vào việc học tiếp theo và form dễ đọc hơn.

Mới: [không gian học flashcard và luyện nghe](docs/LEARNING_WORKSPACE.md), có tua lại, tốc độ nghe, giọng đọc dự phòng và nghe lại khi xem lời giải.

Kho mới: [3.016 thẻ từ và 5.058 câu luyện toàn dự án](docs/VOCABULARY_3000.md), gồm 2.000 từ bổ sung và 4.000 câu chọn nghĩa/điền từ. Nội dung gốc có AI hỗ trợ, nhãn CEFR tạm thời; có liên kết tra Cambridge, chưa phải bộ Cambridge chính thức.

## Chạy trên máy cá nhân

Yêu cầu Python 3.12 trở lên.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py seed_starter_content
python manage.py seed_advanced_content
python manage.py seed_vocabulary_3000 --publish-provisional
python manage.py seed_toeic_workplace --publish-provisional
python manage.py createsuperuser
python manage.py runserver
```

Mở `http://127.0.0.1:8000/`. Tạo người học qua giao diện, hoặc dùng `/admin/` để quản lý học liệu. Đặt biến môi trường trực tiếp, hoặc sao chép `.env.example` thành `.env` rồi nạp tệp trước khi chạy (Bash: `set -a; source .env; set +a`; PowerShell: `$env:DJANGO_SECRET_KEY='...'; $env:DJANGO_DEBUG='true'`). Django không nạp `.env` tự động. Khi phát triển cục bộ, các giá trị mặc định cho phép chạy nhanh.

Sau khi đăng nhập, người học có thể đặt mức CEFR thủ công hoặc mở **Xếp trình độ** để làm bài 15 câu. Bài lấy từ flashcard đã xuất bản, khử lặp lemma giữa các mức và có 3 câu mỗi mức A1–C1; cần tối thiểu 3 từ khác nhau/mức. Kết quả chỉ cập nhật hồ sơ khi người học chủ động chọn áp dụng. Đây là bài ước lượng vốn từ demo, chưa được chuẩn hóa/kiểm định như bài thi CEFR.

Mới: [luyện lại câu sai](docs/MISTAKE_REVIEW.md) trong nhóm tối đa 10 câu, tự lưu/khôi phục lựa chọn, xem kết quả riêng và tiếp tục các câu cần ôn. Bản cập nhật lưu nháp cần chạy migration0011 bằng `python manage.py migrate`. Lượt ôn góp vào lịch hoạt động, không tăng điểm bài gốc hoặc tỷ lệ đúng theo kỹ năng.

Sau mỗi bài Reading/Listening, các câu sai được lưu vào **Sổ lỗi cá nhân**. Người học có thể lọc lỗi mới/đã ôn và theo loại, xem đáp án đúng cùng giải thích, ghi chú nguyên nhân, đánh dấu đã ôn hoặc hỏi trợ lý về câu cụ thể. Mỗi mục gắn với lượt luyện của chính người học; migration tạo mục sổ lỗi cho các câu sai đã lưu từ trước.

## Trợ lý học tập

Mới: [TOEIC AI Tutor trên Cloudflare Workers AI](docs/CLOUDFLARE_AI_TUTOR.md), 4 thao tác nhanh, sổ tay 8 chủ điểm, lịch sử riêng (tối đa 50 lượt), tiến độ và nhiệm vụ từ dữ liệu thật. Cập nhật cần backup rồi chạy `python manage.py migrate` đến migration0020. Worker có AI binding, endpoint nội bộ có khóa và giới hạn lượt toàn hệ thống; mặc định chưa bật gọi model. Chưa triển khai hoặc gọi Workers AI thật.


Bản mới có lựa chọn tra cứu/AI, thẻ nguồn mở lại được, gợi ý theo mức hiện tại và bước hỏi lại khi một từ có nhiều nghĩa đồng điểm. Xem [bản cập nhật và kết quả đo hiện tại](docs/TUTOR_V2.md): trên bộ test mới, từ chối đúng câu ngoài phạm vi tăng 0/8 → 2/8, nhưng Recall@3 giảm 77,5% → 70%. Chưa đủ để quảng bá trợ lý như gia sư đáng tin cậy. [Báo cáo vòng trước](docs/AI_RETRIEVAL.md) được giữ làm lịch sử.

Khi chưa cấu hình nhà cung cấp AI, trợ lý tra cứu học liệu đã xuất bản và các ghi chú ngữ pháp tự biên soạn, rồi trả về nguồn gốc. Mặc định là **Tra cứu học liệu**, kể cả khi có API key: không gọi AI và không tiêu hao lượt. Chỉ khi người học chọn **AI diễn giải**, đã tìm thấy nguồn phù hợp và không cần hỏi lại nghĩa của từ, hệ thống mới gửi câu hỏi tối đa 500 ký tự cùng một số đoạn học liệu liên quan tới nhà cung cấp đã chọn (`openai` hoặc `cloudflare`). Không gửi thông tin tài khoản, điểm số hay toàn bộ lịch sử trò chuyện. Cần thông báo cho người thử nghiệm và cân nhắc quyền riêng tư trước khi bật tích hợp bên ngoài.

## Gợi ý kế hoạch

`planner/services.py` hiện là recommender luật xác định phiên bản `rule-v2-cefr`: dùng kết quả luyện trong 30 ngày, trình độ CEFR hiện tại/mục tiêu, từ đã đến hạn, độ khó, mức đa dạng và giới hạn phút/ngày. Khi ít nhất 80% từ ở mức hiện tại có lần đánh giá gần nhất là “đã nhớ” và chưa vượt mức mục tiêu, planner có thể thêm bộ từ ở mức kế tiếp. Mốc đến hạn ôn không tự làm mất trạng thái này; nếu người học đánh giá lại là “khó” hoặc “chưa nhớ” thì từ đó không còn tính vào tỷ lệ. A1–C1 là nhãn phân loại học liệu tham khảo, không phải phép quy đổi điểm TOEIC chính thức. Đây là baseline giải thích được, chưa phải mô hình máy học đã huấn luyện; ngưỡng 80% là giả thuyết thiết kế cần đánh giá với người học.

## Bản nâng cấp sau audit

Đợt tiếp theo đã có [lưu nháp, tiếp tục bài và tổng kết hoạt động](docs/STUDENT_JOURNEY.md): lựa chọn được tự động lưu theo tài khoản, mở lại bài sẽ khôi phục bản nháp; dashboard ưu tiên bài đang dở và nhiệm vụ chưa hoàn thành. Trang tiến độ có hoạt động 7 ngày và tỷ lệ đúng theo kỹ năng trong 30 ngày. Xem [đề xuất phát triển của các agent](docs/PRODUCT_BACKLOG.md) để theo dõi phần đã làm và các bước tiếp theo.

Xem [ghi chú nâng cấp](docs/UPGRADE_2026-10-19.md). Đã bổ sung lịch ôn thích ứng, lịch ôn 7 ngày, thư viện bài luyện có lọc/phân trang và 8 bài Reading/Listening B1–B2 tự biên soạn (32 câu). Trước bộ mở rộng 3.000+, sau ba lệnh seed cũ, dự án có 1.016 flashcard và 1.058 câu hỏi: 1.000 Vocabulary, 30 Reading, 28 Listening. Bốn bài Listening mới đi kèm MP3 giọng tổng hợp. Mức B1/B2 là nhãn biên tập tham khảo; chưa có giáo viên phê duyệt hoặc hiệu chuẩn.

Lịch ôn: “Chưa nhớ” trở lại sau 10 phút; “Còn khó” điều chỉnh khoảng ôn thận trọng; các lượt “Đã nhớ” đến hạn liên tiếp đi từ 1 ngày, 3 ngày rồi nhân theo hệ số từng thẻ, tối đa 180 ngày. Bấm lặp “Đã nhớ” trước hạn không tăng khoảng ôn. Đây là heuristic đồ án, không phải FSRS hoặc triển khai SM-2 chuẩn. Migration giữ lịch sử/trạng thái hiện có và khởi tạo các trường thích ứng mới; không suy ngược lịch sử thành mức thành thạo.

## Quản trị và nhập từ vựng CSV

Trong `/admin/`, mở **Learning → Flashcards** rồi chọn **Nhập từ vựng CSV**. Tệp cần UTF-8 (có thể có BOM), tối đa 2 MB. Cột bắt buộc: `term,meaning_vi,cefr_level`; cột tùy chọn: `part_of_speech,topic,example_en,example_vi,pronunciation,audio_url`. `cefr_level` chỉ nhận A1, A2, B1, B2 hoặc C1. Màn hình nhập yêu cầu khai báo tên nguồn và quyền sử dụng; bộ học liệu luôn được nhập ở trạng thái nháp để người quản trị kiểm tra rồi mới xuất bản.

Ví dụ CSV tự biên soạn:

```csv
term,meaning_vi,cefr_level,part_of_speech,topic,example_en,example_vi
reliable,đáng tin cậy,B1,adjective,Work,The supplier is reliable.,Nhà cung cấp đáng tin cậy.
```

Chỉ nhập nội dung tự biên soạn hoặc nội dung có quyền sử dụng phù hợp. Không nhập chép từ Cambridge, ETS hoặc nguồn có bản quyền nếu chưa được cấp phép. Nguồn/quyền được lưu trên bộ học liệu và từng flashcard để phục vụ kiểm tra.

Xem [chính sách biên tập học liệu](docs/CONTENT_QUALITY.md) để biết cách tham chiếu CEFR, ETS và British Council, checklist rà soát cùng giới hạn sử dụng từ điển/danh sách từ.

Trợ lý dùng khớp từ khóa trên nội dung đã xuất bản, không phải tìm kiếm ngữ nghĩa/embedding. Khi bật LLM, mô hình chỉ được gọi khi tìm thấy nguồn đáp ứng điều kiện tối thiểu về số từ trùng; nếu không có nguồn phù hợp, hệ thống trả thông báo chưa tìm thấy học liệu.

Truy xuất dùng điều kiện tối thiểu về số từ trùng, không phải ngưỡng xác suất đã được hiệu chuẩn. Lời giải/đáp án câu hỏi chỉ được dùng làm nguồn cho người học đã nộp câu đó trong lượt luyện của chính mình; thẻ từ vựng vẫn có thể tra cứu như kiến thức học tập. Khi người học chủ động chọn AI, mặc định mỗi tài khoản được 20 request/ngày và 3 request/60 giây; toàn ứng dụng dùng chung 200 request/ngày và 20 request/60 giây qua DB cho cả OpenAI, Cloudflare và admin soạn nháp. Ngày tính theo múi giờ Django. Chỉ đặt lượt khi nguồn, cấu trúc ngữ cảnh và cấu hình dịch vụ hợp lệ; request đã đặt kể cả lỗi vẫn tính, không tự retry. Dùng `AI_TUTOR_ENABLED=false` để tắt; thay các biến `AI_TUTOR_*_LIMIT` để điều chỉnh. Cloudflare có thêm Durable Object theo ngày UTC. Đây là hạn mức request, không phải trần hóa đơn. Xem [chi tiết M3](docs/STABILITY_M3.md).

## Audit và các bản ổn định — 24/10/2026

Bản [M2 — bảo mật, chất lượng quiz và giao diện](docs/STABILITY_M2.md) bổ sung quota auth dùng DB chung, quyền CSV parent, no-store trang cá nhân, lọc recall trùng cue và giữ bộ lọc khi chuyển nguồn/đánh giá flashcard. Cần migrate 0019 trước khi chạy; cấu hình proxy Cloudflare và học liệu giáo viên duyệt vẫn cần nghiệm thu riêng.

Xem [audit toàn dự án ngày 23/10](docs/AUDIT_PLAN_2026-10-23.md), [các sửa đổi M1 và hướng dẫn nâng cấp](docs/STABILITY_M1.md), cùng [kiểm tra mã nguồn và cổng phát hành](docs/CI.md). M1 bổ sung chống ghi đè bản nháp practice/ôn câu sai, lưu nguyên bản kết quả mới, sửa lịch ôn sớm và giữ nhiệm vụ đã hoàn thành. Lịch sử bài luyện có liên kết mở lại và phân trang.

Các ghi nhận ở đợt audit 19/10 dưới đây là nền tảng trước M1:

Xem [báo cáo audit](docs/AUDIT_2026-10-19.md) để biết phạm vi, lỗi đã sửa và các điểm còn mở. Audit có đủ 8 vai trò; kiểm tra mã nguồn và luồng HTTP không thay thế kiểm tra giao diện thực tế trên các trình duyệt.

- Kế hoạch ngày không tự thêm bài mới sau mỗi lần hoàn thành và không chọn task vượt số phút/ngày. Nếu không có bài vừa thời lượng, kế hoạch có thể rỗng.
- Lọc flashcard theo CEFR/chủ đề không tự chuyển sang chế độ xem toàn thư viện; cần chọn “Xem toàn bộ từ vựng” để xem thẻ chưa đến hạn.
- Nội dung `draft` không được phục vụ qua bài luyện, flashcard, planner hoặc trợ lý, kể cả khi cờ xuất bản bị đặt sai. `language_checked` vẫn là nội dung demo AI rà soát sơ bộ; không phải phê duyệt của giáo viên.
- Sửa học liệu trong admin hoặc nhập lại CSV xóa trạng thái duyệt cũ, gỡ xuất bản và yêu cầu rà soát lại. Nhập CSV là **gộp/cập nhật**, không tự xóa những từ vắng mặt trong tệp.
- Lượt đang làm có câu hỏi thay đổi hoặc học liệu bị gỡ xuất bản sẽ dừng, không chấm trên mẫu số sai. Lượt practice nộp từ M1 lưu snapshot đề, lựa chọn, đáp án và lời giải; kết quả cũ chưa có snapshot được ghi chú rõ, không được tái dựng giả thành bản gốc.

## Cấu hình trước khi triển khai

Đã bổ sung cấu hình Django production, Gunicorn, WhiteNoise, PostgreSQL qua `DATABASE_URL`, Dockerfile chạy non-root và Worker Cloudflare Containers. Xem [hướng dẫn triển khai Cloudflare](docs/DEPLOY_CLOUDFLARE.md) và `.env.production.example`. Production từ chối secret thiếu/ngắn và database khác PostgreSQL. SSL redirect/cookie Secure mặc định bật; HSTS mặc định một năm, mẫu triển khai đặt 0 trong giai đoạn xác minh HTTPS. Chưa có deployment hoặc URL production được xác nhận; cần hoàn tất xác thực tài khoản, PostgreSQL và kiểm thử hạ tầng thật.

## Kiểm tra

```bash
python manage.py check
python manage.py test
node --test scripts/test_*.cjs
python manage.py evaluate_retrieval  # mặc định dev, không gọi LLM
```

## Trạng thái phạm vi

- Đã có: đăng ký/đăng nhập, dashboard, flashcard A1–C1, bài xếp mức từ vựng, lưu lịch ôn, bài Reading trắc nghiệm, chấm điểm phía máy chủ, giải thích từng phương án, sổ lỗi cá nhân, tiến độ, gợi ý kế hoạch rule-based.
- `seed_starter_content` nạp 1.000 mục từ/cụm từ A1–C1 (79 A1, 235 A2, 286 B1, 263 B2, 137 C1) và tạo 1.000 câu hỏi chọn nghĩa từ. Mỗi lượt trắc nghiệm có tối đa 20 câu; thẻ có thể tìm theo từ/nghĩa/ví dụ và lọc theo mức/chủ đề. Trong 1.000 mục, 152 thẻ nền tảng là nội dung tự biên soạn ban đầu; 848 mục mở rộng được AI hỗ trợ soạn thảo và cần giáo viên rà soát. CEFR là nhãn tạm thời, không phải danh sách Cambridge hoặc chuẩn hóa điểm thi. Bộ seed còn có 12 câu Reading và 12 Listening; `seed_demo` thêm 16 thẻ và 2 câu Reading để minh họa. Chạy cả hai lệnh có 1.016 flashcard và 1.026 câu hỏi (1.000 Vocabulary, 14 Reading, 12 Listening). Listening đi kèm MP3 giọng tổng hợp, có giọng đọc thiết bị và transcript dự phòng; đây không phải bản thu người bản ngữ.
- Flashcard có hai mặt lật 3D: mặt trước dùng để tự nhớ từ và nghe phát âm qua giọng đọc thiết bị; mặt sau hiển thị nghĩa, câu ví dụ, bản dịch và ba nút đánh giá để xếp lịch ôn. Đây là phần tử tương tác phía trình duyệt.
- Agent biên tập tiếng Anh đã rà soát tính tự nhiên cơ bản, sự khớp nhau giữa đoạn nghe/đọc và đáp án, và mức CEFR sơ bộ. Đây chưa phải hiệu chuẩn CEFR bởi đơn vị khảo thí hoặc kiểm định người học.
- Trợ lý có RAG từ kho nội dung và diễn giải bằng LLM khi bật API; cần bộ test chất lượng riêng trước khi dùng như tính năng sản phẩm.
- Đây là gói nội dung khởi đầu để kiểm tra luồng học; chưa đủ cho hành trình từ mất gốc đến TOEIC 750–900 hoặc IELTS B1–C1. Cần tiếp tục biên soạn và rà soát nhiều từ, bài đọc, audio có quyền sử dụng, đề luyện theo từng phần và bài thi thử đủ độ dài; sau đó đánh giá với người học và báo cáo kết quả.
