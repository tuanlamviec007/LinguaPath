# LinguaPath — Audit dự án và kế hoạch phát triển
Ngày audit: **23/10/2026** · Phạm vi: bản mã và dữ liệu hiện có trong workspace.

Tiến độ sau audit, **24/10/2026**: [M1](STABILITY_M1.md), [M2](STABILITY_M2.md), [đợt AI M3](STABILITY_M3.md) và [đợt M4](STABILITY_M4.md). Xem [bảng trạng thái 33 mục](AUDIT_STATUS_2026-10-24.md) cho tình trạng hiện tại. M4 thêm projection từ yếu D07, metric phân tầng C07, log O04, lock/hash O05 và cải thiện C04/G01; nghiệm thu chuyên môn, PG/CI/staging/model vẫn còn mở. Tên đợt bàn giao không có nghĩa milestone vận hành W6–W8 đã hoàn thành. Các phát hiện/số liệu bên dưới giữ bối cảnh audit ban đầu.

## 1. Kết luận để ra quyết định

Dự án đã có vòng học khá đầy đủ: mục tiêu → flashcard/SRS → practice/quiz → lời giải → sổ lỗi/từ yếu → ôn lại, cùng XP, streak và huy hiệu. Quiz có snapshot bất biến, bản nháp theo revision, giới hạn thưởng và kiểm tra quyền sở hữu tốt. Có thể tiếp tục trên kiến trúc Django hiện tại; chưa có bằng chứng cần viết lại bằng một framework khác.

**Ưu tiên phát triển tiếp theo là bảo toàn dữ liệu học, sửa lịch học và chấm công bằng.** Hai lỗi đã tái hiện liên quan trực tiếp đến tính toàn vẹn: practice bị tab cũ ghi đè bản nháp; kết quả practice cũ hiển thị đề/đáp án mới sau khi biên tập nguồn. Một số hành vi SRS, planner và lịch sử cũng sai ở các tình huống biên.

Trước public beta cần thêm kiểm soát đăng nhập/đăng ký, bộ học liệu pilot có người duyệt, kiểm chứng PostgreSQL/Cloudflare thật và vận hành phục hồi. AI Tutor cần được đánh giá lại trên kho hiện tại: việc có trích nguồn chưa bảo đảm nguồn đúng ý định hoặc đầy đủ đáp án.

**Không phát hiện P0 trong phạm vi đã kiểm tra.** Đây không phải chứng nhận không có lỗ hổng. Mã ứng dụng và DB chính không được sửa trong đợt audit; các thao tác tạo/sửa dữ liệu để tái hiện đều dùng DB test hoặc DB memory riêng. Không deploy, không đăng nhập Cloudflare và không gọi model/API trả phí.

## 2. Cách audit và giới hạn

Sáu agent thực hiện song song; agent chính đối chiếu, chạy toàn bộ test, chạy lại các tái hiện backend và kiểm tra trình duyệt:

| Agent | Phạm vi chính |
|---|---|
| audit_backend | Models, practice, quiz, bản nháp, lịch sử, SRS, planner, chi phí truy vấn |
| audit_security | Ownership, CSRF, quyền admin, auth abuse, cache, AI bridge |
| audit_ux | Hành trình, frontend, keyboard/focus, CSS, accessibility |
| audit_content | Kiểm kê DB, CSV, recall, CEFR, placement và độ phủ học liệu |
| audit_ai | Retrieval, router, context, quota, provenance, benchmark và phạm vi đánh giá model |
| audit_ops | Build, CI, PostgreSQL, container, Cloudflare, health, logging và phục hồi |

Phân loại:

- **Đã tái hiện:** có tình huống cụ thể trên DB cô lập hoặc trình duyệt.
- **Xác nhận từ mã/dữ liệu:** đường thực thi hoặc bản ghi thể hiện vấn đề; không đồng nghĩa đã đo ảnh hưởng production.
- **Điều kiện phát hành:** thiếu bằng chứng/kiểm soát trước khi mở rộng; không khẳng định hệ thống đã thất bại.
- **Giới hạn sản phẩm:** hành vi hiện tại có thể chủ ý, cần quyết định sản phẩm hoặc pilot.

P1: cần xử lý trước khi mở rộng tính năng/phát hành phần liên quan. P2: ưu tiên đợt ổn định và pilot. P3: hoàn thiện hành trình/hardening sau các lỗi quan trọng.

**Giới hạn quan trọng:** test chạy trên SQLite; chưa kiểm tra khóa hàng/concurrency trên PostgreSQL thật. Browser QA dùng HTML render từ template hiện tại và fixture giả lập, phục vụ tĩnh; không phải E2E browser–Django đầy đủ. Đã kiểm tra desktop, chưa kiểm tra điện thoại thật, bàn phím ảo hoặc screen reader. Rà ngôn ngữ thủ công chỉ gồm 30 thẻ (6/mức) và 8 mẫu Reading/Listening; không phải duyệt toàn kho. Không có kết quả pentest production, load test production, CVE scan đầy đủ hoặc đánh giá suy luận model thật.

## 3. Bằng chứng kiểm tra hiện tại

| Kiểm tra | Kết quả |
|---|---|
| Django toàn bộ | **380/380 đạt**, 63,950 giây |
| JavaScript toàn bộ | **67/67 đạt**, khoảng 5,96 giây |
| Django system check | Không có vấn đề |
| Migration drift | No changes detected |
| pip check | Không có dependency bị hỏng |
| Production check với cấu hình giả, DB URL không kết nối | Exit 0; còn W005/W021 cho HSTS subdomains/preload; không chứng minh PostgreSQL vận hành |
| Tái hiện backend độc lập ở agent chính | Xác nhận mất nháp, kết quả biến đổi, Hard tăng 180 ngày, mất task, lịch sử cũ và quét snapshot tăng theo lịch sử |
| Trình duyệt template hiện tại | Xác nhận href đổi nguồn vẫn giữ mode cũ; recall input thiếu liên kết nghĩa; màu số câu 11px tương phản thấp |
| Cài npm sạch offline trong thư mục tạm | Không hoàn tất do ENOTCACHED youch-core@0.3.3; giới hạn cache môi trường, chưa có bằng chứng lock bị hỏng |

Lệnh kiểm tra chuẩn:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python -m pip check
.venv/bin/python manage.py test
node --test scripts/test_*.cjs
.venv/bin/python manage.py evaluate_retrieval --benchmark-version 2 --include-test --output /tmp/retrieval-audit.json
```

Việc 447 test hiện tại đều đạt nhưng các lỗi mới vẫn tái hiện cho thấy cần thêm regression theo tình huống thực tế, đặc biệt hai tab, sửa học liệu sau khi nộp và lịch sử lớn. Không lấy số lượng test làm thước đo đầy đủ về chất lượng.

### Kiểm kê học liệu

| Chỉ số | Hiện tại |
|---|---:|
| Bộ đã xuất bản | 429 |
| Vocabulary / Reading / Listening | 408 / 11 / 10 |
| language_checked / teacher_approved | **429 / 0** |
| Flashcard / lemma phân biệt | 3.056 / 3.052 |
| A1 / A2 / B1 / B2 / C1 | 359 / 678 / 899 / 848 / 272 |
| Câu vocabulary / Reading / Listening | 5.080 / 30 / 28 |
| Câu có đúng 4 lựa chọn và 1 khóa đúng | 5.138 / 5.138 |
| Thẻ đủ điều kiện thuật toán quiz nghĩa | 3.056, tối đa 3.052 lemma sau khử trùng |
| Thẻ đủ điều kiện recall | 3.037, tương ứng 3.033 lemma |
| Thẻ bị loại recall do nghĩa chứa đáp án | 19, bộ lọc đang hoạt động đúng |

Bốn lemma lặp available, arrive, invite, repair thuộc nguồn/ngữ cảnh khác nhau; không mặc định xem là lỗi. Tất cả reviewer hiện ghi AI/chưa giáo viên duyệt. Trạng thái trên chỉ chứng minh **chưa có xác nhận chuyên môn được ghi nhận trong hệ thống**, không suy đoán hoạt động ngoài hệ thống.

## 4. Phát hiện backend và tính toàn vẹn

### D01 · P1 · Kết quả practice cũ biến đổi theo nguồn — đã tái hiện, tin cậy cao

Bằng chứng: [models.py](sandbox:/workspace/scratch/a50a630aa056/learning/models.py) dòng 173; [views.py](sandbox:/workspace/scratch/a50a630aa056/learning/views.py) dòng 591; [result.html](sandbox:/workspace/scratch/a50a630aa056/templates/learning/result.html) dòng 31.

AttemptAnswer lưu correctness lịch sử nhưng hiển thị qua Question/AnswerOption hiện tại. Tái hiện: nộp A đúng → đổi wording và chuyển khóa đúng sang B → mở kết quả cũ. Điểm vẫn 100% và nhãn “Đúng”, trong khi đề/đáp án đã đổi và A hiện là sai.

**Sửa:** snapshot bất biến khi submit, gồm đề, lựa chọn, đáp án đã chọn, khóa đúng, lời giải và phiên bản nguồn. Có chính sách rõ với dữ liệu cũ không thể khôi phục nguyên văn.

**Nghiệm thu:** chỉnh sửa/xóa option nguồn không đổi nội dung kết quả đã nộp; lịch sử và notebook thể hiện cùng một bằng chứng. Không tự khẳng định snapshot backfill là đề gốc nếu chỉ còn dữ liệu hiện tại.

### D02 · P1 · Tab cũ ghi đè bản nháp mới — đã tái hiện, tin cậy cao

Bằng chứng: [practice_sessions.py](sandbox:/workspace/scratch/a50a630aa056/learning/practice_sessions.py) dòng 139, 191; [practice-draft.js](sandbox:/workspace/scratch/a50a630aa056/static/js/practice-draft.js) dòng 80, 193. Có khoảng trống tương tự cần bao phủ ở [mistake_review.py](sandbox:/workspace/scratch/a50a630aa056/learning/mistake_review.py) dòng 307.

Payload là toàn bộ lựa chọn nhưng không có revision server. Tab A lưu 1 đáp án, tab B cũ gửi {}: cả hai thành công, số đáp án giữ lại **1 → 0**. BFCache còn tự lên lịch lưu trang vừa khôi phục. Cảnh báo “nên làm trên một tab” đã có nhưng không ngăn mất dữ liệu.

**Sửa:** optimistic concurrency/CAS cho practice và mistake review; xử lý conflict và BFCache theo quiz hiện có. Kiểm tra cả race giữa save và submit.

**Nghiệm thu:** hai tab cùng revision N không thể cùng ghi thành công; request cũ nhận 409 và không sửa dữ liệu mới. Submit idempotent, không ghi sau submit; trình duyệt giữ lựa chọn để người dùng phục hồi.

### D03 · P2 · Autosave practice thiếu timeout — xác nhận mã, tin cậy cao

Bằng chứng: practice-draft.js dòng 80–100 và 132–140. Request treo giữ requestInFlight=true, làm nút lưu bị khóa và thay đổi mới chờ vô hạn.

**Nghiệm thu:** có timeout hữu hạn; hủy request treo, giữ dirty state và đáp án, mở lại thao tác lưu; thông báo rõ trạng thái chưa được lưu. Test mạng treo, lỗi tạm thời và phục hồi.

### D04 · P2 · “Khó” liên tiếp đẩy thẻ ra xa 180 ngày — đã tái hiện

Bằng chứng: views.py dòng 391; [spaced_repetition.py](sandbox:/workspace/scratch/a50a630aa056/learning/spaced_repetition.py) dòng 37. Chặn tăng khoảng ôn sớm chỉ áp dụng known; hard vẫn ceil(interval×1,2).

31 POST hard không đổi thời gian làm khoảng ôn **1 → 180 ngày**, review_count=31. Đây là lỗi lập lịch; chưa có bằng chứng vượt trần XP, vì thưởng đã có giới hạn khác.

**Nghiệm thu:** hard trước hạn không tăng interval hoặc đẩy due_at xa thêm; review đúng hạn vẫn theo thuật toán; giữ hành vi relearning hữu ích của again. Có test lặp request và double click.

### D05 · P2 · Lưu mục tiêu xóa task đã hoàn thành — đã tái hiện

Bằng chứng: views.py dòng 99–105; [planner/services.py](sandbox:/workspace/scratch/a50a630aa056/planner/services.py) dòng 29. Mọi POST hợp lệ xóa toàn bộ task hôm nay, dù không đổi thời gian/CEFR hoặc chỉ đổi target score.

**Nghiệm thu:** lưu không đổi/đổi score giữ nguyên task hoàn thành và ID; chỉ tái lập phần chưa hoàn thành khi đầu vào planner thật sự đổi; thời gian đã học vẫn trừ vào ngân sách còn lại.

### D06 · P2 · “Các lượt gần đây” có thể là lượt cũ, không có đường mở lại đầy đủ — đã tái hiện

Bằng chứng: views.py dòng 115–117, 139; [progress.html](sandbox:/workspace/scratch/a50a630aa056/templates/learning/progress.html) dòng 89–95; dashboard.html dòng 140.

Query không order, Python sum tải toàn bộ lịch sử rồi mới lấy 20. Với 28 lượt, lượt mới nhất không nằm trong danh sách; SQL SELECT không ORDER BY/LIMIT. Giao diện còn thiếu link kết quả và phân trang practice.

**Nghiệm thu:** aggregate tổng ở DB; danh sách metadata order theo submitted_at rồi PK giảm dần; phân trang; mỗi lượt có link kết quả đúng chủ sở hữu. Với >20 lượt vẫn mở được lượt mới và lượt cũ; số row hydrate được giới hạn.

### D07 · P2 · Đếm từ yếu quét mọi snapshot trong lịch sử — benchmark cô lập

Bằng chứng: [quiz_weak_words.py](sandbox:/workspace/scratch/a50a630aa056/learning/quiz_weak_words.py) dòng 37–55; dashboard/progress/quiz hub đều gọi helper.

Agent chính chạy lại với 3.000 thẻ, 15 câu/phiên, snapshot khoảng 30 KB/phiên, 3 lần đo/mức:

| Phiên lịch sử | Số query | Median local |
|---:|---:|---:|
| 10 | 2 | 81,9 ms |
| 1.000 | 2 | 229,1 ms |
| 5.000 | 2 | 942,4 ms |

Ở 5.000 phiên helper decode 75.000 câu, khoảng **151 MB JSON**, để trả cùng 15 từ yếu. Lần đo agent khác cao hơn; đây là bằng chứng tăng theo payload, không phải dự báo latency production hoặc benchmark p95.

**Nghiệm thu:** materialize latest outcome theo user/card/identity khi submit; backfill idempotent; dashboard count không SELECT snapshot; giữ semantics sửa nguồn/từ đúng xóa lỗi/từ sai mở lại. Đo PostgreSQL và query plan trên lịch sử lớn trước rollout. Chưa thấy conventional N+1 trong các đường đã rà; nút thắt chính là khối lượng dữ liệu.

## 5. Bảo mật và quyền riêng tư

### S01 · P1, điều kiện public beta · Chưa kiểm soát auth abuse

Bằng chứng: [config/urls.py](sandbox:/workspace/scratch/a50a630aa056/config/urls.py) dòng 26–27; views.py dòng 45–56; [settings.py](sandbox:/workspace/scratch/a50a630aa056/config/settings.py) dòng 82–91.

DB memory với CSRF hợp lệ: 12 lần đăng nhập sai đều trả 200, 8 đăng ký liên tiếp đều tạo tài khoản và trả 302. Chưa có throttling ứng dụng được quan sát. Nhiều tài khoản vượt ý nghĩa quota theo tài khoản; global Worker cap vẫn giới hạn tổng request ở nhánh Cloudflare.

**Nghiệm thu:** giới hạn theo IP và định danh, delay/challenge tăng dần cho login/signup/admin và khôi phục tài khoản nếu bật. Vượt ngưỡng nhận 429/challenge; không cho attacker khóa dài hạn tài khoản nạn nhân. Kiểm tra đúng IP sau trusted proxy.

### S02 · P2 · Import CSV vượt quyền parent LearningContent — đã tái hiện

Bằng chứng: [admin.py](sandbox:/workspace/scratch/a50a630aa056/learning/admin.py) dòng 228–230; [vocabulary_import.py](sandbox:/workspace/scratch/a50a630aa056/learning/vocabulary_import.py) dòng 53–76.

Staff chỉ có add/change Flashcard bị 403 ở LearningContent admin nhưng import CSV trả 302 và tạo parent. Điều kiện khai thác là staff có quyền giới hạn; không phải lỗ hổng cho học viên thường.

**Nghiệm thu:** kiểm tra quyền tạo/chỉnh parent tương ứng hoặc quyền import được định nghĩa rõ. Thiếu quyền phải 403 và không thay đổi row; test ma trận biên tập/duyệt/import.

### S03 · P3 · Cache policy trang cá nhân không đồng nhất — hardening

Dashboard/progress/goal/flashcards trả Vary:Cookie nhưng thiếu Cache-Control; quiz/tutor có no-store/private. Chưa chứng minh lộ dữ liệu giữa người dùng.

**Nghiệm thu:** policy private,no-store cho HTML/JSON cá nhân, đặc biệt draft/result; test headers và hành trình đăng xuất trên máy dùng chung. Bổ sung chính sách retention/export/xóa tài khoản và dữ liệu gửi provider ở gói privacy; đây là công việc hoàn thiện, chưa kết luận vi phạm pháp lý.

Điểm mạnh: ownership phía server, CSRF, redirect bookmark kiểm tra same-origin, quiz DTO allowlist, unique constraints/transaction cho thưởng, bridge secret/HTTPS allowlist/no redirect và global budget. Không phát hiện đường IDOR/SSRF/XSS trực tiếp trong phần đã rà.

## 6. Học liệu và đo tiến bộ

### C01 · P1, điều kiện pilot · Chưa có xác nhận chuyên môn trong DB

429/429 bộ xuất bản ở language_checked, **0 teacher_approved**. UI đã nói nội dung AI hỗ trợ và CEFR tham khảo; không có cơ sở báo cáo giả mạo chứng nhận ETS/Cambridge.

**Nghiệm thu:** chọn bộ pilot có phạm vi rõ, duyệt sense/đáp án/nhiễu/CEFR bởi người đủ chuyên môn; lưu người duyệt, ngày, phiên bản và checklist. Agent hỗ trợ sàng lọc, không tự thay thế phê duyệt chuyên môn.

### C02 · P1 · Recall có prompt không xác định một đáp án — đã tái hiện

Bằng chứng: [quiz_answers.py](sandbox:/workspace/scratch/a50a630aa056/learning/quiz_answers.py) dòng 27–32; [quiz_views.py](sandbox:/workspace/scratch/a50a630aa056/learning/quiz_views.py) dòng 55–58.

Thẻ #100 speak và #1305 say cùng A1, verb, nghĩa “nói”, gợi ý “s · 1 từ”; đáp án say cho prompt speak bị chấm False. Có 4 nhóm/8 thẻ trùng nghĩa + POS + chữ đầu/số từ: speak/say, customer/client, store/shop, coworker/colleague. Một số cặp có thể khác level, nên không nói tất cả xuất hiện cùng một bộ lọc; riêng speak/say trùng cả level.

**Nghiệm thu:** thêm ngữ cảnh phân biệt đã duyệt, accepted forms có biên tập hoặc loại tạm mục mơ hồ. Không dùng fuzzy matching rộng để hợp thức hóa mọi từ đồng nghĩa. Test toàn kho và các đáp án hợp lý do giáo viên cung cấp; không tạo weak-word sai vì prompt mơ hồ.

### C03 · P2 · CSV lỗi đã làm hỏng bản ghi #778 trip

Bằng chứng: [expanded_vocabulary.csv](sandbox:/workspace/scratch/a50a630aa056/learning/data/expanded_vocabulary.csv) dòng 458; [seed_starter_content.py](sandbox:/workspace/scratch/a50a630aa056/learning/management/commands/seed_starter_content.py) dòng 198–202.

Dấu phẩy không quote làm example_vi còn “Cuối tuần trước”, topic thành phần còn lại của câu, Travel bị đẩy sang cột thừa.

**Nghiệm thu:** validator từ chối sai số cột trước ghi; sửa nguồn và cập nhật dữ liệu có kiểm soát; chạy lại seed không tái tạo lỗi; rà tất cả CSV cũ. Không tự ghi đè hàng loạt phần người biên tập đã sửa.

### C04 · P2, giới hạn đo lường · Placement chưa được hiệu chuẩn

15 câu nhận nghĩa, 3/mức; đạt ≥2/3 ở các mức liên tiếp để chọn mức và ghi current_cefr. Không đại diện đầy đủ CEFR/kỹ năng thi, và nhãn đầu vào chưa có giáo viên duyệt.

**Nghiệm thu:** ngân hàng placement riêng có blueprint, độ khó/khả năng phân biệt/độ ổn định từ pilot; gọi rõ ước lượng vốn từ; người học có thể chọn bắt đầu dễ hơn hoặc đánh giá lại.

### C05 · P2, giới hạn nội dung · Thiếu chiều sâu Reading/Listening

98,9% câu hỏi là vocabulary; chỉ 30 Reading/28 Listening, chưa có R/L C1 và metadata blueprint theo TOEIC Part. Điều này là độ phủ hiện tại, không mặc định cần C1 cho mọi mục tiêu người dùng. Có 45 thẻ dùng hai khung ví dụ chung ít thể hiện sense.

**Nghiệm thu:** blueprint theo kỹ năng/dạng bài/ngữ cảnh do giáo viên chốt; ưu tiên nhóm người học pilot; đặt số item tối thiểu theo blueprint, thay ví dụ chung và đo kết quả theo kỹ năng. Chưa quảng bá như đề thi chuẩn hóa.

### C06 · P2, giới hạn pedagogy · Mở mức dựa self-rating

planner/services.py dòng 51–63 dùng ≥80% thẻ có last_rating=known để mở thêm mức kế; không yêu cầu nhớ sau khoảng trễ. Đây là mở phạm vi nội dung, **không tự nâng current_cefr**.

**Nghiệm thu:** phân biệt tự đánh giá và bằng chứng nhớ trễ; pilot điều kiện mastery có giải thích, vẫn cho người học thử mức khó chủ động.

### C07 · P2 · Accuracy tổng trộn mode/nguồn khác độ khó

[quiz_progress.py](sandbox:/workspace/scratch/a50a630aa056/learning/quiz_progress.py) dòng 17–24 gộp mọi first try (meaning/recall, all/saved).

**Nghiệm thu:** tách nhận biết và tự nhớ theo mode/level/nguồn; tổng chỉ mô tả hoạt động. Thay đổi tỷ lệ do test mix không được gọi là tăng/giảm năng lực.

## 7. AI Tutor

### Benchmark chạy lại

Retriever improved hiện tại, bộ v2 AI-editorial gold:

| Chỉ số | Dev | Test | Toàn bộ |
|---|---:|---:|---:|
| Query dương / âm | 40 / 8 | 40 / 8 | 80 / 16 |
| Recall@3 | 30/40 = 75% | **27/40 = 67,5%** | 57/80 = 71,25% |
| MRR@3 | 0,725 | 0,675 | 0,700 |
| Từ chối đúng query âm | 3/8 | **2/8** | 5/16 |
| Query âm trả nguồn sai | 5/8 | 6/8 | 11/16 |

Nhóm Vietnamese paraphrase: **2/20 = 10% Recall@3**. Retriever previous trên cùng kho đạt Recall@3 toàn bộ 77,5%, test 75%, nhưng từ chối đúng 0/16 query âm: có tradeoff, không thể chọn chỉ bằng một metric.

Đây là **retrieval theo headword**, chưa đo đúng sense, chất lượng lời giải, semantic RAG hoặc kết quả học. Test v2 đã được mở trong audit; không được tiếp tục tune rồi gọi nó là holdout mới. Report cũ dùng 1.016 thẻ, hiện có 3.056.

### A01 · P1 khi bật AI · Context bị cắt mất đáp án và lời giải

Bằng chứng: [ai.py](sandbox:/workspace/scratch/a50a630aa056/learning/ai.py) dòng 81; [retrieval.py](sandbox:/workspace/scratch/a50a630aa056/learning/retrieval.py) dòng 165–178.

Mỗi source bị cắt 1.800 ký tự trước trần tổng 5.400. Passage/script/transcript đứng trước explanation/options. 32 câu xuất bản có source >1.800; q1206 dài 3.837, explanation ở offset 3.415 và options ở 3.568, nên payload không gửi phần này cho model.

**Nghiệm thu:** context có cấu trúc ưu tiên stem/options/key/explanation; bỏ transcript trùng; chỉ cắt stimulus theo ngân sách còn lại. Regression kiểm tra payload thực gửi provider với q1206 và Reading dài, không cần gọi model.

### A02 · P1, điều kiện AI pilot · Retrieval và số liệu công bố chưa đủ tin cậy

Tỷ lệ trên cho thấy nguồn sai ở câu không liên quan và recall yếu với diễn đạt tiếng Việt. Docs hiện không phản ánh corpus mới.

**Nghiệm thu:** cập nhật fingerprint; tập đánh giá mới được con người duyệt, có sense/intent/negative và đi qua production router. Mục tiêu khởi điểm đề xuất để hiệu chuẩn cùng giáo viên: ≥85% Recall@3 trên query dương, ≥90% từ chối đúng query âm; báo riêng từng nhóm. Đây là mục tiêu dự án đề xuất, không phải chuẩn chung hay kết quả đã đạt.

### A03 · P2 · Router dùng trigger đầu tiên, làm lệch ý định

ai.py dòng 15–18; [tutor_knowledge.py](sandbox:/workspace/scratch/a50a630aa056/learning/tutor_knowledge.py) dòng 74–81.

Production router: “Compare present perfect and passive voice” chỉ trả Hiện tại hoàn thành; “What is the reading on this thermometer?” trả Cách luyện Reading. Evaluator gọi retrieve_context trực tiếp nên không bắt lỗi router.

**Nghiệm thu:** phân loại intent, hỗ trợ nhiều chủ đề phù hợp, từ chối incidental trigger; thêm test qua entry point sản phẩm.

### A04 · P2 · Tutor history thiếu source/version provenance

ai.py dòng 22–29 bỏ source IDs/version; views.py dòng 272–278 replay TutorTurn.result. Nguồn bị sửa/thu hồi không được đối chiếu khi mở lịch sử.

**Nghiệm thu:** lưu nguồn/phiên bản/model/prompt; gắn ngày snapshot; cảnh báo nguồn đã thay đổi hoặc thực thi chính sách thu hồi rõ ràng. Ownership đang được kiểm tra; đây không phải phát hiện lộ dữ liệu chéo user. Giữ lịch sử có thể là chủ ý, cần quyết định semantics trước khi sửa.

### A05 · P2, có điều kiện · OpenAI không qua global Worker quota

ai.py dòng 66–100 gọi OpenAI trực tiếp sau quota per-user; ledger global nằm ở [ai-gateway.js](sandbox:/workspace/scratch/a50a630aa056/deploy/cloudflare/ai-gateway.js) dòng 75–97. Tài liệu đã ghi giới hạn này.

**Nghiệm thu:** public deployment chọn một nhánh được kiểm soát; tắt OpenAI nếu chưa có global reservation, hoặc áp cùng quota/kill switch cho cả provider. Test concurrency và failure charging. Giới hạn request không được mô tả là giới hạn tiền thanh toán tuyệt đối.

### A06 · P2, điều kiện bật inference · Chưa có nghiệm thu model thật

Test provider mock inference; evaluator chỉ đo lexical retrieval; schema draft không chứng minh nội dung đúng. Chưa có exploit prompt injection đã chứng minh trong audit.

**Nghiệm thu:** sau khi được phép dùng tài nguyên, chạy bộ model eval có trần ngân sách: nguồn dài, nguồn sai, abstention, injection đa ngôn ngữ, claim không hỗ trợ, lời giải distractor và ambiguity. Ghi model/prompt chính xác, có người chấm độc lập. Giữ AI exercise ở draft cho đến duyệt.

Điểm mạnh cần giữ: lookup mặc định, fail closed question ID, chỉ giải thích câu đã nộp của đúng user, model không quyết định điểm/planner, timeout/no retry/no redirect và fallback học liệu khi provider lỗi.

## 8. UX và giao diện

### U01 · P2 · Liên kết prompt recall và tương phản cần sửa

Bằng chứng: [quiz_play.html](sandbox:/workspace/scratch/a50a630aa056/templates/learning/quiz_play.html) dòng 26–27; [quiz.js](sandbox:/workspace/scratch/a50a630aa056/static/js/quiz.js) dòng 79–87; [quiz.css](sandbox:/workspace/scratch/a50a630aa056/static/css/quiz.css) dòng 4; quiz-recall.css dòng 28,43.

Browser xác nhận khi chuyển câu, input nhận focus nhưng accessible label chung; aria-describedby chỉ gồm rule và hint, không có nghĩa tiếng Việt. Chưa chạy screen reader thực.

Màu đáp án nhỏ #6f7f61 trên #fcfcf7 khoảng 4,18:1; số câu chưa trả lời #89967a trên #f9faf4 khoảng 2,98:1. Browser xác nhận số câu 11px dùng đúng cặp màu này. Placeholder khoảng 3,67:1; desktop input computed 23px normal, cũng cần rà tiêu chuẩn và trạng thái thực tế.

**Nghiệm thu:** input liên kết nghĩa và số câu; screen reader đọc đủ đề sau chuyển; chữ nhỏ thiết yếu ≥4,5:1, focus rõ, kiểm tra mọi trạng thái. Giữ bright theme hiện tại, tập trung readability và nhất quán token.

### U02 · P2 · Rating flashcard mất bộ lọc/ngữ cảnh

views.py dòng 393,410 redirect về content + level, không giữ library/search/topic/page. Học từ thư viện bất kỳ có thể bị chuyển sang bộ riêng của thẻ.

**Nghiệm thu:** giữ context hợp lệ và tiếp tục đúng bộ đang học; next URL phải same-origin; không làm mất tiến độ điều hướng.

### U03 · P3 · Đổi nguồn quiz mất lựa chọn chưa submit

[quiz_hub.html](sandbox:/workspace/scratch/a50a630aa056/templates/learning/quiz_hub.html) dòng 24,27–31. Browser: chọn recall + B1 +15 câu, link Sổ cá nhân vẫn là ?source=saved&mode=meaning.

**Nghiệm thu:** giữ mode/level/topic/count hợp lệ khi đổi nguồn; giải thích trường hợp filter không còn phù hợp.

Desktop practice sau chuyển đến câu 3 không thấy header bị che trong fixture hiện tại. Chưa kết luận các nghi vấn mobile: sticky savebar, Enter với bàn phím ảo và thứ tự đọc sau flip flashcard. Đưa vào checklist thiết bị, không báo là lỗi đã tái hiện.

Điểm mạnh: skip link/landmark, fieldset/legend, live status, reduced motion và inert cho mặt thẻ ẩn. Không có Figma file/link được cung cấp cho audit; không khẳng định đã đối chiếu thiết kế Figma.

## 9. Triển khai và duy trì

### O01 · P1, điều kiện phát hành · Production chưa được chứng minh

[DEPLOY_CLOUDFLARE.md](sandbox:/workspace/scratch/a50a630aa056/docs/DEPLOY_CLOUDFLARE.md) dòng 5,17,95 ghi rõ chưa có bằng chứng triển khai. Môi trường audit thiếu Docker CLI. Chưa kiểm tra PostgreSQL thật, image chạy thật, HTTPS/session/CSRF qua Worker, restart persistence, backup restore và tải đồng thời.

**Nghiệm thu:** staging có release ID/image, chạy migration, hành trình đăng ký→học→submit→logout, restart vẫn giữ dữ liệu, restore độc lập và rollback được diễn tập. Đây là thiếu bằng chứng, không khẳng định Cloudflare cấu hình hiện tại chắc chắn lỗi.

### O02 · P2 · Chưa có Git/CI làm cổng regression

Không có Git repository/CI config trong bản làm việc được audit. Không suy đoán về repo ngoài môi trường chưa được cung cấp.

**Nghiệm thu:** đưa mã vào source control; CI Django + toàn bộ Node + migration drift + static build + production check, PostgreSQL service và concurrency tests thích hợp. Mỗi release gắn commit/image.

### O03 · P2 · Health 200 dù DB chưa có schema — đã tái hiện

[config/health.py](sandbox:/workspace/scratch/a50a630aa056/config/health.py) dòng 9–17 chỉ SELECT 1. DB tạm rỗng có 0 table và 39 migration chưa áp dụng vẫn trả 200.

**Nghiệm thu:** tách liveness/readiness; release gate kiểm tra migration/schema cần thiết trước nhận traffic. Test DB rỗng/sai schema phải không ready. Không migrate trong mỗi request.

### O04 · P2 · Thiếu quan sát và cảnh báo vận hành

[wrangler.jsonc](sandbox:/workspace/scratch/a50a630aa056/deploy/cloudflare/wrangler.jsonc) dòng 37 tắt observability; router.js dòng 24–29 catch lỗi mà không ghi sự kiện chẩn đoán; chưa có cấu hình app logging/alert đầy đủ.

**Nghiệm thu:** log có request correlation và redaction; uptime/readiness probe; cảnh báo 5xx/latency/DB/AI usage; runbook có chủ sở hữu. Không log prompt/token/secret tùy tiện.

### O05 · P2 · Build Python chưa tái lập hoàn toàn

requirements pin direct dependency, chưa lock/hash transitive; [Dockerfile](sandbox:/workspace/scratch/a50a630aa056/Dockerfile) dùng mutable python:3.12-slim.

**Nghiệm thu:** lock có hash, ghi digest image phát hành, quy trình cập nhật base/dependency và build sạch. Không suy diễn có CVE từ việc chưa có lock.

### O06 · P3 · Lệnh test README bỏ sót suite

README dòng 124 không gồm quiz/saved words/Workers AI. Nghiệm thu: một lệnh aggregate dùng cả docs và CI: node --test scripts/test_*.cjs.

Điểm mạnh: production fail closed khi secret/DB sai; cookie/HTTPS mặc định an toàn; image chạy nonroot, không copy DB/secret; không tự seed/migrate lúc startup; ingress kiểm tra hostname và ghi đè TLS header không tin cậy.

## 10. Giới hạn chức năng bổ sung

**G01 · P3 · Listening chỉ có script chưa có mistake-retry.** Có thể xuất bản, làm sai và vào notebook nhưng eligible_retry_count=0 vì retry yêu cầu audio URL. Test hiện tại chủ ý giữ hành vi này, nên không gọi là regression.

Nghiệm thu: TTS retry bằng DTO an toàn hoặc giải thích giới hạn và có đường quay lại practice hữu ích; không làm lộ transcript chứa đáp án.

## 11. Kế hoạch phát triển có thứ tự

Ước lượng là **ngày kỹ sư tập trung**, gồm sửa/test/review trong từng gói; không phải ngày lịch và không cộng thêm các estimate chồng lặp của từng agent. Chưa bao gồm chờ tài khoản/hạ tầng hoặc duyệt toàn kho.

| Gói | Kết quả cần bàn giao | Liên quan | Ước lượng | Phụ thuộc |
|---|---|---|---:|---|
| W0 | Git/CI, test aggregate, PostgreSQL test service, lock/release ID, migration gate cơ bản | O02,O03,O05,O06 | 2–3 ngày | Có repository/runner khi triển khai |
| W1 | Snapshot practice, CAS practice/mistake review, timeout/BFCache/save-submit race, legacy policy | D01,D02,D03 | 4–6 ngày | Chốt snapshot/revision schema; W0 để kiểm tra PG |
| W2 | Early-rating policy, giữ task done, lịch sử practice đúng thứ tự/link/pagination | D04,D05,D06 | 2–3 ngày | Quy tắc early Hard và ngân sách còn lại |
| W3 | Auth throttling, importer permission matrix, no-store, privacy flow tối thiểu | S01,S02,S03 | 3–5 ngày | Chọn nguồn IP tin cậy và nhóm quyền |
| W4 | CSV strict validation, sửa nguồn/dữ liệu có kiểm soát, ambiguity recall, workflow duyệt pilot | C01,C02,C03 | 3–5 ngày kỹ thuật + 2–4 ngày giáo viên | Chốt phạm vi pilot/sense/accepted forms |
| W5 | Recall accessible prompt, contrast, giữ filter flashcard/quiz, thiết bị test matrix | U01,U02,U03 | 2–3 ngày | W1 ổn định lifecycle |
| W6 | Materialized weak-word outcomes, backfill/reconcile và query/load kiểm chứng | D07 | 3–5 ngày | Content identity/version policy, W0 |
| W7 | AI context/provenance/quota/router, benchmark mới, prompt/model version và bounded pilot | A01–A06 | 7–11 ngày kỹ thuật + 2–3 ngày reviewer | W3,W4; tài nguyên inference chỉ dùng khi được phép |
| W8 | Staging Cloudflare/PostgreSQL thật, health/logs/alerts, backup/restore/rollback/load acceptance | O01,O03,O04 | 5–8 ngày | W0–W5; tài khoản/DB/Docker runner sẵn sàng |

**Tổng lõi W0–W8: 31–49 ngày kỹ sư + 4–7 ngày chuyên môn**, có thể chạy song song một phần. Đây là khoảng dự toán để lập nguồn lực, không phải cam kết lịch phát hành. W4 chỉ duyệt bộ pilot được chọn, không bao gồm 3.056 thẻ/5.138 câu.

### Mốc hoàn thành

| Mốc | Phạm vi | Điều kiện qua mốc |
|---|---|---|
| M1 — Học không mất dữ liệu | W0,W1,W2 · 8–12 ngày kỹ sư | Tái hiện D01–D06 chuyển thành regression đạt; không mất nháp, không đổi kết quả cũ, không xóa task done; CI/PG kiểm tra phần transaction liên quan |
| M2 — Pilot có kiểm soát | W3,W4,W5 · 8–13 ngày kỹ sư + duyệt | Chặn auth abuse; ma trận quyền đúng; pilot content được duyệt; recall công bằng; hành trình và accessibility thiết yếu đạt |
| M3 — Vận hành và AI có bằng chứng | W6,W7,W8 · 15–24 ngày kỹ sư + reviewer | Dashboard không quét snapshot lịch sử; retrieval/model eval đạt mục tiêu đã chốt; staging, restore, rollback và monitoring có biên bản |

Nếu pilot chưa cần inference, có thể hoàn thành W6/W8 và giữ Tutor ở lookup; việc mở inference phải có nghiệm thu riêng W7. Không cần chờ AI để xác minh vòng học deterministic.

### Sau mốc ổn định

| Hướng | Kết quả | Dự toán ban đầu |
|---|---|---|
| Đo tiến bộ có cơ sở | Phân tầng metric C07, placement bank riêng C04, nhớ trễ cho planner C06 | 4–6 ngày kỹ thuật + 2–3 ngày chuyên môn; pilot 2–3 tuần |
| Chiều sâu Reading/Listening | Blueprint theo mục tiêu, metadata dạng bài, stimulus/đáp án/lời giải đã duyệt, thay ví dụ chung | 5–8 ngày kỹ thuật + 10–20 ngày biên soạn/duyệt lô đầu; quy mô chốt sau blueprint |
| Gamification gắn việc học | Quest dựa học đúng hạn/recall sau trễ, giải thích XP rõ, không dùng XP như mức năng lực | Chốt sau pilot; giữ trần thưởng và chống lặp hiện tại |
| Listening retry | TTS retry hoặc đường thay thế có ích cho script-only | 1–2 ngày kỹ thuật sau quyết định UX/audio |

Chưa ưu tiên thêm hàng nghìn từ, leaderboard công khai hoặc thêm provider AI. Dữ liệu hiện tại ủng hộ tăng độ tin cậy và chiều sâu học tập trước.

## 12. Chia việc cho agent ở vòng phát triển

Đây là phân công đề xuất cho giai đoạn triển khai kế tiếp; đợt hiện tại chỉ audit và lập kế hoạch.

| Vai trò | Sở hữu | Quy tắc tích hợp |
|---|---|---|
| Agent backend | W1 schema/services, W2 SRS/planner/history, W6 outcome projection | Một owner cho migration; chốt hợp đồng revision/snapshot trước khi frontend sửa |
| Agent frontend | W1 client, W5, link lịch sử W2 | Dựa API thống nhất; test timeout/conflict/IME/keyboard/BFCache |
| Agent content | W4 validator, báo cáo ambiguity và hàng đợi review | Không tự teacher_approved; sửa nguồn có truy vết và bảo toàn chỉnh sửa thủ công |
| Agent security | W3, review quota W7, kiểm tra quyền/headers | Kiểm tra độc lập đường lỗi và ma trận quyền |
| Agent AI | W7 packing/router/provenance/evaluation | Test payload offline trước; không gọi model tùy tiện; dùng holdout mới |
| Agent ops | W0,W8 | Chuẩn bị artifact/runbook; staging acceptance có bằng chứng |
| Agent chính | Hợp nhất contract, review migration, kiểm tra end-to-end và release gates | Tích hợp từng gói nhỏ; không cho nhiều agent sửa cùng file/migration không phối hợp |

Không chia nhiều agent sửa đồng thời learning/views.py. Tách theo module hoặc tuần tự merge; agent kiểm tra độc lập dùng DB riêng. Mỗi gói phải có diff review, regression từ lỗi thực và kết quả kiểm tra có phạm vi rõ.

## 13. Checklist nghiệm thu phát hành

- [ ] Không còn P1 mở trong phạm vi sẽ phát hành; P2 hoãn có người chịu trách nhiệm và lý do.
- [ ] Practice/quiz save–submit–retry–back–hai tab không mất hoặc nhân đôi bằng chứng/thưởng.
- [ ] Kết quả lịch sử bất biến; dữ liệu legacy được gắn giới hạn trung thực.
- [ ] Nội dung pilot được người có chuyên môn duyệt theo phiên bản; recall ambiguity được xử lý.
- [ ] Auth/signup/admin throttling và importer permissions được test.
- [ ] Mobile thật, keyboard, screen reader, contrast và lỗi mạng được kiểm tra; không chỉ screenshot đẹp.
- [ ] PostgreSQL transaction/concurrency và migration nâng cấp dữ liệu thật được diễn tập.
- [ ] Container/Worker HTTPS, session/CSRF, cold start và restart persistence có kết quả.
- [ ] Backup phục hồi sang môi trường riêng; rollback tương thích schema; mục tiêu RPO/RTO được chốt và đo.
- [ ] Logs/alerts có redaction và runbook; có người nhận xử lý.
- [ ] Nếu bật inference: context đầy đủ, quota chung/kill switch, bộ eval mới và nguồn/version truy vết được.
- [ ] Tài liệu phản ánh đúng capability đã kiểm chứng và giới hạn còn lại.

## 14. Dấu vết phiên bản và tài liệu đối chiếu

SHA256 tại thời điểm audit:

```text
LinguaPath-gamification-quiz.zip
bab86089b53bc145c7f447074ced5e42fb1d02aa3c4f3cf322c4c0778e2ce8fc
db.sqlite3
263136fd118b98db96b299c277116ff4da69cd955bac855b762fdb8427f698ed
learning/views.py
ae01fee95b18a7b33fe73654044e5e29644696f95f7cfec037c5f811b98c1144
learning/quiz_views.py
8d60d45fd8efd1cf689b6c24652af8dc3e74ef80f4cff16ca3236a446e125b45
static/js/practice-draft.js
7a20b463e0a805ec8272c8d1f1cf82a7e9a10e58c7865fe8e99fbc8767d10810
benchmark v2
e8bd2bb26e8336cb213b002ffaa7ce9e5445033ffb0088d99112c19b9c756fd6
retriever improved
c45bc92cd927340a84f5ede62e15f38f4d4f6f7f2524762fe25255772988f76a
retrieval corpus
e7d55856b206e1954399e935dd65d35ef89f8ee984b7dfa93be020b161804805
```

Nguồn chính thức được đối chiếu ngày 23/10/2026:

1. [Django 5.2 security](https://docs.djangoproject.com/en/5.2/topics/security/) — Django không tự throttle authentication; dự án cần lớp kiểm soát bổ sung.
2. [Django 5.2 QuerySet / select_for_update](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update) — SQLite không thực thi SELECT FOR UPDATE; cần TransactionTestCase/backend phù hợp để kiểm tra hành vi khóa.
3. [Cloudflare Containers — Get started](https://developers.cloudflare.com/containers/get-started/) — build/deploy container thông thường cần Docker, và Worker trả lời chưa tự chứng minh container đã sẵn sàng.

Các phát hiện cụ thể dựa trên mã, DB và tái hiện của bản dự án này. Nguồn ngoài chỉ đối chiếu hành vi nền tảng; không thay thế kiểm chứng production.

