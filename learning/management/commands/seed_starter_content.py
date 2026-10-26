from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from learning.models import AnswerOption, Flashcard, LearningContent, Question
from learning.strict_csv import read_strict_csv
from learning.vocabulary_import import normalized_term, validate_vocabulary_rows


EXPANDED_PATH = Path(__file__).resolve().parents[2] / 'data' / 'expanded_vocabulary.csv'
EXPANDED_COLUMNS = {'term', 'cefr_level', 'part_of_speech', 'meaning_vi', 'example_en', 'example_vi', 'topic'}


def load_expanded_rows(path=None):
    try:
        text = Path(path or EXPANDED_PATH).read_text(encoding='utf-8-sig')
        rows = validate_vocabulary_rows(
            read_strict_csv(text, required_columns=EXPANDED_COLUMNS), required_fields=EXPANDED_COLUMNS,
        )
        if len(rows) != 848:
            raise ValueError(f'Ngân hàng expanded cần đủ 848 từ, hiện có {len(rows)}.')
        return rows
    except (OSError, ValueError) as exc:
        raise CommandError(str(exc)) from exc


class Command(BaseCommand):
    help = 'Load original A1-C1 vocabulary, vocabulary exercises, Reading, and Listening practice.'

    @transaction.atomic
    def handle(self, *args, **options):
        # Reject malformed source before even renaming or creating a parent.
        expanded_rows = load_expanded_rows()
        self._preserve_existing = True
        legacy_title = 'Nền tảng A1–A2: Từ vựng cho học tập và đời sống'
        vocab_title = 'Ngân hàng từ vựng A1–C1: Học tập và đời sống'
        legacy = LearningContent.objects.filter(title=legacy_title, exam_type='TOEIC', content_type='vocabulary').first()
        existing = LearningContent.objects.filter(title=vocab_title, exam_type='TOEIC', content_type='vocabulary').first()
        if legacy and existing and legacy.id != existing.id:
            raise CommandError('Có cả bộ legacy và bộ hiện tại; cần hợp nhất thủ công để giữ chỉnh sửa và lịch sử.')
        if legacy and legacy.title != vocab_title:
            legacy.title = vocab_title
            legacy.save(update_fields=['title', 'updated_at'])

        vocab = self._upsert_content(vocab_title, {
            'description': 'Thẻ từ vựng tự biên soạn về đời sống, học tập, công việc và giao tiếp. Mức CEFR theo từng từ là tham khảo sơ bộ; đây không phải danh sách TOEIC chuẩn hoặc Cambridge.',
            'exam_type': 'TOEIC', 'content_type': 'vocabulary', 'skill': 'vocabulary', 'topic': 'Everyday English',
            'difficulty': 1, 'estimated_minutes': 16, 'source_name': 'Tự biên soạn; mức từ đối chiếu sơ bộ với English Vocabulary Profile',
            'source_url': 'https://englishprofile.org/?menu=english-vocabulary-profile',
            'rights_note': 'Bộ gồm 152 thẻ tự biên soạn và 848 mục AI hỗ trợ soạn thảo; nghĩa, ví dụ và mức CEFR cần giảng viên rà soát trước khi dùng làm học liệu chính thức. Không sao chép Cambridge/ETS.',
            'is_published': True,
        }, 'Đã rà soát sơ bộ nghĩa, từ loại, tự nhiên của ví dụ và sense bị gộp. Mức CEFR vẫn provisional; cần kiểm tra sense-level, pilot với người học và giảng viên duyệt.')
        words = [
            ('address','A1','noun','địa chỉ','What is your new address?','Địa chỉ mới của bạn là gì?','Personal information'),
            ('afternoon','A1','noun','buổi chiều','The library is open in the afternoon.','Thư viện mở cửa vào buổi chiều.','Time'),
            ('answer','A1','noun','câu trả lời','Please write your answer here.','Vui lòng viết câu trả lời ở đây.','Study'),
            ('arrive','A1','verb','đến nơi','The bus arrives at eight.','Xe buýt đến lúc tám giờ.','Travel'),
            ('breakfast','A1','noun','bữa sáng','I have breakfast before class.','Tôi ăn sáng trước giờ học.','Food'),
            ('building','A1','noun','tòa nhà','The computer lab is in this building.','Phòng máy tính ở trong tòa nhà này.','Places'),
            ('busy','A1','adjective','bận rộn','My teacher is busy this morning.','Giáo viên của tôi bận sáng nay.','People'),
            ('careful','A1','adjective','cẩn thận','Be careful with the hot tea.','Hãy cẩn thận với trà nóng.','Daily life'),
            ('classmate','A1','noun','bạn cùng lớp','My classmate helped me with the exercise.','Bạn cùng lớp đã giúp tôi làm bài tập.','Study'),
            ('close','A1','verb','đóng cửa','The shop closes at six.','Cửa hàng đóng cửa lúc sáu giờ.','Daily life'),
            ('comfortable','A1','adjective','thoải mái','These shoes are comfortable for walking.','Đôi giày này thoải mái để đi bộ.','Shopping'),
            ('delicious','A1','adjective','ngon','The soup is delicious.','Món súp rất ngon.','Food'),
            ('early','A1','adverb','sớm','We arrived early for the exam.','Chúng tôi đến sớm để dự thi.','Time'),
            ('email','A1','verb','gửi email','I will email you the notes.','Tôi sẽ gửi ghi chú cho bạn qua email.','Communication'),
            ('exercise','A1','noun','bài tập học tập','Complete exercise three at home.','Hãy hoàn thành bài tập số ba ở nhà.','Study'),
            ('family','A1','noun','gia đình','Her family lives in Thai Nguyen.','Gia đình cô ấy sống ở Thái Nguyên.','People'),
            ('free','A1','adjective','rảnh','Are you free after class?','Bạn có rảnh sau giờ học không?','Time'),
            ('help','A1','verb','giúp đỡ','Could you help me find the room?','Bạn có thể giúp tôi tìm phòng không?','Communication'),
            ('homework','A1','noun','bài tập về nhà','I finished my English homework.','Tôi đã làm xong bài tập tiếng Anh.','Study'),
            ('important','A1','adjective','quan trọng','Sleep is important before an exam.','Giấc ngủ rất quan trọng trước kỳ thi.','Study'),
            ('join','A1','verb','tham gia','Would you like to join our study group?','Bạn có muốn tham gia nhóm học của chúng tôi không?','Study'),
            ('message','A1','noun','tin nhắn','I left a message for Linh.','Tôi đã để lại tin nhắn cho Linh.','Communication'),
            ('often','A1','adverb','thường xuyên','We often study in the library.','Chúng tôi thường học ở thư viện.','Study'),
            ('practice','A1','verb','luyện tập','I practice English for twenty minutes a day.','Tôi luyện tiếng Anh hai mươi phút mỗi ngày.','Study'),
            ('appointment','A2','noun','cuộc hẹn','I have a dentist appointment on Friday.','Tôi có lịch hẹn nha sĩ vào thứ Sáu.','Health'),
            ('borrow','A2','verb','mượn','Can I borrow your dictionary?','Tôi có thể mượn từ điển của bạn không?','Study'),
            ('cancel','A2','verb','hủy','They had to cancel the meeting.','Họ phải hủy cuộc họp.','Work'),
            ('change','A2','verb','thay đổi','Please tell me if the room number changes.','Vui lòng cho tôi biết nếu số phòng thay đổi.','Study'),
            ('choose','A2','verb','chọn','Choose the best answer.','Hãy chọn đáp án tốt nhất.','Study'),
            ('customer','A2','noun','khách hàng','The customer asked about the price.','Khách hàng hỏi về giá.','Work'),
            ('deliver','A2','verb','giao hàng','The store delivers food to our dormitory.','Cửa hàng giao đồ ăn đến ký túc xá.','Shopping'),
            ('describe','A2','verb','miêu tả','Describe your hometown in three sentences.','Hãy miêu tả quê bạn bằng ba câu.','Study'),
            ('different','A2','adjective','khác nhau','We have different plans for the weekend.','Chúng tôi có những kế hoạch khác nhau cho cuối tuần.','Daily life'),
            ('enough','A2','determiner','đủ','We have enough time to review.','Chúng ta có đủ thời gian để ôn tập.','Study'),
            ('experience','A2','noun','kinh nghiệm','She has experience working with children.','Cô ấy có kinh nghiệm làm việc với trẻ em.','Work'),
            ('improve','A2','verb','cải thiện','Listening every day can improve your English.','Nghe mỗi ngày có thể cải thiện tiếng Anh của bạn.','Study'),
            ('include','A2','verb','bao gồm','The course includes weekly speaking practice.','Khóa học bao gồm luyện nói hằng tuần.','Study'),
            ('information','A2','noun','thông tin','You can find the information on the website.','Bạn có thể tìm thông tin trên trang web.','Communication'),
            ('lend','A2','verb','cho mượn','Could you lend me a pen?','Bạn có thể cho tôi mượn một cây bút không?','Study'),
            ('offer','A2','verb','cung cấp','The school offers free evening classes.','Trường cung cấp các lớp học buổi tối miễn phí.','Study'),
            ('prepare','A2','verb','chuẩn bị','I prepare my notes before the lesson.','Tôi chuẩn bị ghi chú trước buổi học.','Study'),
            ('return','A2','verb','trả lại','Please return the book by Monday.','Vui lòng trả sách trước thứ Hai.','Study'),
            ('suggest','A2','verb','đề xuất, gợi ý','I suggest taking a short break.','Tôi đề xuất nghỉ giải lao một chút.','Daily life'),
            ('usually','A2','adverb','thường thường','The first bus usually leaves at six.','Chuyến xe buýt đầu tiên thường khởi hành lúc sáu giờ.','Travel'),
            ('cousin','A1','noun','anh/chị/em họ','My cousin studies at the same college as I do.','Anh/chị/em họ của tôi học cùng trường cao đẳng với tôi.','Family'),
            ('kitchen','A1','noun','nhà bếp','There is a small table in the kitchen.','Có một chiếc bàn nhỏ trong nhà bếp.','Home'),
            ('ticket','A1','noun','vé','I bought a bus ticket at the station.','Tôi đã mua một vé xe buýt ở nhà ga.','Travel'),
            ('weather','A1','noun','thời tiết','The weather is warm today.','Hôm nay thời tiết ấm áp.','Weather'),
            ('village','A1','noun','ngôi làng','My grandparents live in a quiet village.','Ông bà tôi sống trong một ngôi làng yên tĩnh.','Places'),
            ('carry','A1','verb','mang, xách','Can you carry this bag for me?','Bạn có thể xách chiếc túi này giúp tôi không?','Daily life'),
            ('market','A1','noun','khu chợ','We buy fresh vegetables at the market.','Chúng tôi mua rau tươi ở chợ.','Shopping'),
            ('tired','A1','adjective','mệt','I feel tired after the long walk.','Tôi cảm thấy mệt sau chuyến đi bộ dài.','Health'),
            ('hungry','A1','adjective','đói','The children are hungry after school.','Bọn trẻ đói sau giờ học.','Food'),
            ('minute','A1','noun','phút','The bus will be here in five minutes.','Xe buýt sẽ đến trong năm phút nữa.','Time'),
            ('repair','A2','verb','sửa chữa','The technician can repair my laptop this afternoon.','Kỹ thuật viên có thể sửa máy tính xách tay của tôi vào chiều nay.','Technology'),
            ('invite','A2','verb','mời','They invited us to a small dinner on Saturday.','Họ mời chúng tôi đến một bữa tối nhỏ vào thứ Bảy.','Social life'),
            ('crowded','A2','adjective','đông đúc','The train is usually crowded after work.','Tàu thường đông đúc sau giờ làm.','Travel'),
            ('miss','A2','verb','lỡ chuyến xe/tàu','We left early because we did not want to miss the last bus.','Chúng tôi rời đi sớm vì không muốn lỡ chuyến xe buýt cuối cùng.','Travel'),
            ('decide','A2','verb','quyết định','I decided to take the morning class.','Tôi đã quyết định học lớp buổi sáng.','Study'),
            ('receipt','A2','noun','biên lai','Keep the receipt in case you need to exchange the shirt.','Hãy giữ biên lai phòng khi bạn cần đổi chiếc áo.','Shopping'),
            ('available','A2','adjective','còn trống','Is the study room available after lunch?','Phòng học nhóm có còn trống sau bữa trưa không?','Study'),
            ('traffic','A2','noun','lượng xe cộ','Heavy traffic made us late for the appointment.','Lượng xe cộ đông khiến chúng tôi đến cuộc hẹn muộn.','Travel'),
            ('directions','A2','plural noun','chỉ dẫn đường','A student gave me directions to the science building.','Một sinh viên đã chỉ đường cho tôi đến tòa nhà khoa học.','Places'),
            ('suddenly','A2','adverb','đột nhiên','It suddenly started to rain during our walk.','Trời đột nhiên bắt đầu mưa khi chúng tôi đang đi bộ.','Weather'),
        ]
        # Additional original everyday and study vocabulary; level labels stay provisional.
        words.extend([
            ('age','A1','noun','tuổi','What age do students start university in your country?','Ở nước bạn, sinh viên bắt đầu học đại học ở độ tuổi nào?','Personal information'),
            ('animal','A1','noun','động vật','The children saw a small animal near the garden.','Bọn trẻ nhìn thấy một con vật nhỏ gần khu vườn.','Nature'),
            ('begin','A1','verb','bắt đầu','Our English class begins at half past eight.','Lớp tiếng Anh của chúng tôi bắt đầu lúc tám giờ rưỡi.','Study'),
            ('birthday','A1','noun','sinh nhật','Her birthday is in the middle of July.','Sinh nhật của cô ấy vào giữa tháng Bảy.','Personal information'),
            ('bus','A1','noun','xe buýt','I take the bus to campus every morning.','Tôi đi xe buýt đến trường mỗi sáng.','Travel'),
            ('buy','A1','verb','mua','We need to buy notebooks for the new course.','Chúng tôi cần mua vở cho khóa học mới.','Shopping'),
            ('call','A1','verb','gọi điện','Please call me when you arrive at the station.','Hãy gọi cho tôi khi bạn đến nhà ga.','Communication'),
            ('clean','A1','verb','dọn dẹp, làm sạch','We clean the classroom after the club meeting.','Chúng tôi dọn lớp học sau buổi sinh hoạt câu lạc bộ.','Daily life'),
            ('cook','A1','verb','nấu ăn','My brother can cook a simple dinner.','Anh/em trai tôi có thể nấu một bữa tối đơn giản.','Food'),
            ('dance','A1','verb','nhảy, khiêu vũ','They dance together at the college festival.','Họ cùng nhảy tại lễ hội của trường cao đẳng.','Free time'),
            ('dinner','A1','noun','bữa tối','We usually have dinner at seven.','Chúng tôi thường ăn tối lúc bảy giờ.','Food'),
            ('drink','A1','verb','uống','Remember to drink water during the trip.','Hãy nhớ uống nước trong chuyến đi.','Health'),
            ('finish','A1','verb','hoàn thành, kết thúc','I finish my classes at four o’clock.','Tôi kết thúc các tiết học lúc bốn giờ.','Study'),
            ('friend','A1','noun','bạn bè','A friend helped me find the right classroom.','Một người bạn đã giúp tôi tìm đúng phòng học.','People'),
            ('listen','A1','verb','nghe','Listen to the announcement before you choose an answer.','Hãy nghe thông báo trước khi chọn đáp án.','Study'),
            ('lunch','A1','noun','bữa trưa','The students eat lunch in the main cafeteria.','Sinh viên ăn trưa ở căng tin chính.','Food'),
            ('music','A1','noun','âm nhạc','She listens to music while she studies.','Cô ấy nghe nhạc trong khi học.','Free time'),
            ('open','A1','verb','mở','The library opens at eight on weekdays.','Thư viện mở cửa lúc tám giờ vào các ngày trong tuần.','Places'),
            ('speak','A1','verb','nói','Students speak English in the conversation club.','Sinh viên nói tiếng Anh trong câu lạc bộ giao tiếp.','Study'),
            ('wait','A1','verb','đợi, chờ','Please wait here until the bus arrives.','Vui lòng đợi ở đây đến khi xe buýt đến.','Travel'),
            ('accept','A2','verb','chấp nhận','The school accepted her application for the course.','Trường đã chấp nhận đơn đăng ký khóa học của cô ấy.','Study'),
            ('agree','A2','verb','đồng ý','We agreed to meet after the afternoon class.','Chúng tôi đồng ý gặp nhau sau tiết học buổi chiều.','Communication'),
            ('airport','A2','noun','sân bay','The airport bus leaves every thirty minutes.','Xe buýt sân bay khởi hành mỗi ba mươi phút.','Travel'),
            ('almost','A2','adverb','gần như, suýt','The report is almost ready for the teacher.','Báo cáo gần như đã sẵn sàng để nộp cho giảng viên.','Study'),
            ('amazing','A2','adjective','đáng kinh ngạc, tuyệt vời','The students gave an amazing performance at the festival.','Các sinh viên có màn trình diễn tuyệt vời tại lễ hội.','Free time'),
            ('balcony','A2','noun','ban công','We had breakfast on the balcony.','Chúng tôi ăn sáng ở ban công.','Home'),
            ('bicycle','A2','noun','xe đạp','He rides his bicycle to the language center.','Cậu ấy đi xe đạp đến trung tâm ngoại ngữ.','Travel'),
            ('calendar','A2','noun','lịch','Write the exam date on your calendar.','Hãy ghi ngày thi vào lịch của bạn.','Study'),
            ('celebrate','A2','verb','ăn mừng, kỷ niệm','The class will celebrate the end of the course.','Lớp sẽ ăn mừng khi khóa học kết thúc.','Social life'),
            ('century','A2','noun','thế kỷ','The old building was built in the last century.','Tòa nhà cũ được xây vào thế kỷ trước.','History'),
            ('choice','A2','noun','sự lựa chọn','You have a choice of morning or evening classes.','Bạn có thể chọn lớp buổi sáng hoặc buổi tối.','Study'),
            ('compare','A2','verb','so sánh','Compare your answers with a partner.','Hãy so sánh câu trả lời với một bạn học.','Study'),
            ('conversation','A2','noun','cuộc trò chuyện','We had a short conversation about the project.','Chúng tôi có một cuộc trò chuyện ngắn về dự án.','Communication'),
            ('decision','A2','noun','quyết định','It was a difficult decision to change courses.','Đổi khóa học là một quyết định khó khăn.','Study'),
            ('dictionary','A2','noun','từ điển','Use a dictionary to check the meaning of the word.','Hãy dùng từ điển để kiểm tra nghĩa của từ.','Study'),
            ('during','A2','preposition','trong suốt, trong khi','Please keep your phone off during the lesson.','Vui lòng tắt điện thoại trong suốt buổi học.','Study'),
            ('education','A2','noun','giáo dục','Education can open many opportunities for young people.','Giáo dục có thể mở ra nhiều cơ hội cho người trẻ.','Study'),
            ('electricity','A2','noun','điện','The classroom has no electricity this morning.','Sáng nay lớp học bị mất điện.','Daily life'),
            ('event','A2','noun','sự kiện','The university is holding a career event next week.','Trường đại học tổ chức sự kiện hướng nghiệp vào tuần tới.','Study'),
            ('expensive','A2','adjective','đắt, giá cao','The course book is more expensive at the airport shop.','Sách giáo trình ở cửa hàng sân bay đắt hơn.','Shopping'),
        ])
        words.extend([
            ('apple','A1','noun','quả táo','I put an apple in my bag for the trip.','Tôi để một quả táo vào túi cho chuyến đi.','Food'),
            ('aunt','A1','noun','cô, dì, bác gái','My aunt teaches science at a local school.','Cô tôi dạy khoa học ở một trường địa phương.','Family'),
            ('baby','A1','noun','em bé','The baby is sleeping in the next room.','Em bé đang ngủ ở phòng bên cạnh.','Family'),
            ('bag','A1','noun','túi, cặp','Please put your books in the blue bag.','Hãy để sách vào chiếc túi màu xanh.','Personal items'),
            ('bed','A1','noun','giường','The guest room has a large bed.','Phòng dành cho khách có một chiếc giường lớn.','Home'),
            ('bedroom','A1','noun','phòng ngủ','There are two windows in my bedroom.','Có hai cửa sổ trong phòng ngủ của tôi.','Home'),
            ('black','A1','adjective','màu đen','He bought a black notebook for class.','Cậu ấy mua một quyển vở màu đen cho lớp học.','Colors'),
            ('blue','A1','adjective','màu xanh dương','The blue folder is for English homework.','Chiếc bìa hồ sơ màu xanh dương dùng cho bài tập tiếng Anh.','Colors'),
            ('book','A1','noun','sách, quyển sách','I borrowed a book about local history.','Tôi mượn một quyển sách về lịch sử địa phương.','Study'),
            ('brother','A1','noun','anh/em trai','My brother studies computer science.','Anh/em trai tôi học ngành khoa học máy tính.','Family'),
            ('camera','A1','noun','máy ảnh','She took a camera on the class trip.','Cô ấy mang máy ảnh trong chuyến đi của lớp.','Travel'),
            ('car','A1','noun','ô tô','They drove a car to the countryside.','Họ lái ô tô về vùng nông thôn.','Travel'),
            ('cat','A1','noun','con mèo','The cat is sitting beside the door.','Con mèo đang ngồi cạnh cửa.','Animals'),
            ('chair','A1','noun','ghế','Please take a chair near the window.','Hãy lấy một chiếc ghế gần cửa sổ.','Home'),
            ('class','A1','noun','lớp học, buổi học','Our class has twenty students this term.','Lớp chúng tôi có hai mươi sinh viên trong học kỳ này.','Study'),
            ('clock','A1','noun','đồng hồ','The clock above the board is five minutes fast.','Đồng hồ trên bảng chạy nhanh năm phút.','Time'),
            ('coffee','A1','noun','cà phê','I bought a cup of coffee before the lecture.','Tôi mua một cốc cà phê trước giờ giảng.','Food'),
            ('computer','A1','noun','máy tính','You can use a computer in the study room.','Bạn có thể dùng máy tính trong phòng tự học.','Technology'),
            ('desk','A1','noun','bàn học, bàn làm việc','The teacher left the papers on her desk.','Giảng viên để giấy tờ trên bàn làm việc.','Study'),
            ('doctor','A1','noun','bác sĩ','The doctor will see patients this afternoon.','Bác sĩ sẽ khám cho bệnh nhân vào chiều nay.','Health'),
            ('dog','A1','noun','con chó','Their dog waits outside the house.','Con chó của họ đợi ở bên ngoài ngôi nhà.','Animals'),
            ('door','A1','noun','cửa ra vào','Please close the door quietly.','Vui lòng đóng cửa nhẹ nhàng.','Home'),
            ('father','A1','noun','bố, cha','Her father works at the city hospital.','Bố cô ấy làm việc ở bệnh viện thành phố.','Family'),
            ('floor','A1','noun','sàn nhà, tầng','The language center is on the third floor.','Trung tâm ngoại ngữ ở tầng ba.','Places'),
            ('pencil','A1','noun','bút chì','Use a pencil to write your answers on the practice sheet.','Hãy dùng bút chì để viết đáp án vào phiếu luyện tập.','Study'),
            ('activity','A2','noun','hoạt động','The club planned an outdoor activity for new students.','Câu lạc bộ lên kế hoạch hoạt động ngoài trời cho sinh viên mới.','Study'),
            ('afraid','A2','adjective','sợ, lo ngại','Do not be afraid to ask a question in class.','Đừng ngại đặt câu hỏi trong lớp.','Feelings'),
            ('alone','A2','adjective/adverb','một mình','She studied alone in the library after class.','Cô ấy học một mình trong thư viện sau giờ học.','Study'),
            ('another','A2','determiner/pronoun','một cái/người khác nữa','Could I have another sheet of paper?','Cho tôi xin thêm một tờ giấy nữa được không?','Study'),
            ('around','A2','preposition/adverb','xung quanh, khoảng','The campus tour takes around one hour.','Chuyến tham quan khuôn viên trường kéo dài khoảng một giờ.','Places'),
            ('attention','A2','noun','sự chú ý','Please pay attention to the final instruction.','Vui lòng chú ý đến hướng dẫn cuối cùng.','Study'),
            ('bank','A2','noun','ngân hàng','The bank near campus closes at four.','Ngân hàng gần trường đóng cửa lúc bốn giờ.','Places'),
            ('bottle','A2','noun','chai, lọ','Bring a bottle of water to the sports field.','Hãy mang một chai nước đến sân thể thao.','Daily life'),
            ('break','A2','noun','giờ nghỉ, quãng nghỉ','We have a ten-minute break between lessons.','Chúng tôi có giờ nghỉ mười phút giữa các tiết học.','Study'),
            ('bridge','A2','noun','cây cầu','The bus crosses the bridge before reaching the station.','Xe buýt đi qua cây cầu trước khi đến nhà ga.','Travel'),
            ('broken','A2','adjective','bị hỏng','The printer is broken, so use the one upstairs.','Máy in bị hỏng, vì vậy hãy dùng chiếc ở tầng trên.','Technology'),
            ('business','A2','noun','doanh nghiệp, việc kinh doanh','Her family runs a small food business.','Gia đình cô ấy điều hành một doanh nghiệp thực phẩm nhỏ.','Work'),
            ('center','A2','noun','trung tâm','The test center is beside the main library.','Trung tâm thi nằm cạnh thư viện chính.','Places'),
            ('common','A2','adjective','phổ biến, thường gặp','It is common to feel nervous before an exam.','Cảm thấy lo lắng trước kỳ thi là điều thường gặp.','Study'),
            ('complete','A2','verb/adjective','hoàn thành; đầy đủ','Please complete the form before you meet the advisor.','Vui lòng hoàn thành biểu mẫu trước khi gặp cố vấn.','Study'),
            ('condition','A2','noun','tình trạng, điều kiện','The library asks students to return books in good condition.','Thư viện yêu cầu sinh viên trả sách trong tình trạng tốt.','Study'),
            ('continue','A2','verb','tiếp tục','After lunch, we will continue the group project.','Sau bữa trưa, chúng tôi sẽ tiếp tục dự án nhóm.','Study'),
            ('culture','A2','noun','văn hóa','The international club shares food from different cultures.','Câu lạc bộ quốc tế chia sẻ món ăn từ nhiều nền văn hóa.','Society'),
            ('daily','A2','adjective/adverb','hằng ngày','She keeps a daily record of her study time.','Cô ấy ghi lại thời gian học hằng ngày.','Study'),
            ('dangerous','A2','adjective','nguy hiểm','It is dangerous to cross the road while looking at a phone.','Vừa nhìn điện thoại vừa băng qua đường rất nguy hiểm.','Safety'),
            ('date','A2','noun','ngày, ngày tháng','Check the date of the interview in your email.','Hãy kiểm tra ngày phỏng vấn trong email.','Time'),
            ('dentist','A2','noun','nha sĩ','I have an appointment with the dentist on Tuesday.','Tôi có lịch hẹn với nha sĩ vào thứ Ba.','Health'),
            ('design','A2','noun/verb','thiết kế; bản thiết kế','The students designed a poster for the science fair.','Các sinh viên thiết kế một tấm áp phích cho hội chợ khoa học.','Study'),
        ])
        words.extend(tuple(row[key] for key in ('term', 'cefr_level', 'part_of_speech', 'meaning_vi', 'example_en', 'example_vi', 'topic')) for row in expanded_rows)
        terms = [row[0].casefold() for row in words]
        if len(terms) != len(set(terms)):
            raise CommandError('Từ vựng bị trùng lemma giữa starter và expanded_vocabulary.csv.')
        if len(words) != 1000:
            raise CommandError(f'Ngân hàng expanded cần đủ 1000 từ, hiện có {len(words)}.')
        if vocab._seed_created:
            vocab.description = f'{len(words)} thẻ A1–C1: 152 thẻ nền tảng tự biên soạn và {max(0, len(words) - 152)} mục mở rộng AI hỗ trợ soạn thảo. Nghĩa, ví dụ và mức CEFR cần giảng viên rà soát; đây không phải danh sách Cambridge hoặc bộ đề thi chuẩn.'
            vocab.save(update_fields=['description', 'updated_at'])

        added_cards = 0
        existing_terms = {normalized_term(value) for value in vocab.flashcards.values_list('term', flat=True)}
        for i, row in enumerate(words, 1):
            term, level, pos, meaning, example, vi, topic = row
            term = term.strip()
            if normalized_term(term) in existing_terms:
                continue
            ai_assisted = i > 152
            _, created = Flashcard.objects.get_or_create(content=vocab, term=term, defaults={
                'cefr_level': level, 'topic': topic, 'part_of_speech': pos,
                'meaning_vi': meaning, 'example_en': example, 'example_vi': vi,
                'source_name': 'AI hỗ trợ soạn thảo; cần giảng viên rà soát' if ai_assisted else 'Tự biên soạn',
                'rights_note': 'Nội dung gốc, không sao chép Cambridge/ETS; CEFR tạm thời, cần rà soát ngôn ngữ.' if ai_assisted else 'Từ, nghĩa tiếng Việt và câu ví dụ do nhóm đồ án tự biên soạn; không sao chép danh sách Cambridge.',
                'order': i,
            })
            added_cards += created
            existing_terms.add(normalized_term(term))
        if added_cards and not vocab._seed_created:
            # New children change the reviewed version; keep all editor text,
            # but require a fresh review rather than inheriting old approval.
            vocab.is_published = False
            vocab.review_status = 'draft'
            vocab.reviewer = ''
            vocab.reviewed_at = None
            vocab.review_note = ''
            vocab.source_checked_on = None
            vocab.save(update_fields=['is_published', 'review_status', 'reviewer', 'reviewed_at', 'review_note', 'source_checked_on', 'updated_at'])
        self._vocabulary_quizzes(vocab)

        self._quiz('Reading A1: A notice at the student library', 'reading', 'Đọc thông báo ngắn và tìm thông tin trực tiếp.', 'A1', [
            ('The student library is open from Monday to Friday, 8 a.m. to 7 p.m. On Saturday, it closes at 1 p.m. Students can borrow up to two books for one week. Please return books at the front desk.', 'When does the library close on Saturday?', [('At 1 p.m.','A'),('At 7 p.m.','B'),('At 8 a.m.','C'),('At 1 a.m.','D')], 'A', 'Thông báo ghi thư viện đóng cửa lúc 1 giờ chiều thứ Bảy.'),
            ('The student library is open from Monday to Friday, 8 a.m. to 7 p.m. On Saturday, it closes at 1 p.m. Students can borrow up to two books for one week. Please return books at the front desk.', 'Where should students return books?', [('In the classroom','A'),('At the front desk','B'),('At the café','C'),('At home','D')], 'B', 'Câu cuối yêu cầu trả sách tại quầy phía trước.')])
        self._quiz('Reading A2: A change to the English study group', 'reading', 'Đọc tin nhắn và xác định thay đổi cùng hành động cần làm.', 'A2', [
            ('Hi everyone, our English study group will meet in Room 204 this Thursday, not Room 120. We will start at 5:30 p.m. Please bring your workbook. If you cannot come, send me a message before Wednesday evening. — Mai', 'Where will the group meet?', [('Room 120','A'),('Room 204','B'),('The library','C'),('The café','D')], 'B', 'Tin nhắn cập nhật địa điểm là Room 204.'),
            ('Hi everyone, our English study group will meet in Room 204 this Thursday, not Room 120. We will start at 5:30 p.m. Please bring your workbook. If you cannot come, send me a message before Wednesday evening. — Mai', 'What should a student do if they cannot attend?', [('Call on Thursday','A'),('Bring two workbooks','B'),('Message Mai before Wednesday evening','C'),('Meet in Room 120','D')], 'C', 'Người không thể tham gia cần nhắn trước tối thứ Tư.')])
        self._quiz('Reading A1: A community garden notice', 'reading', 'Đọc thông báo ngắn và tìm thời gian cùng vật cần mang.', 'A1', [
            ('The community garden is open on Sunday from 9 a.m. to noon. Visitors can enter through the blue gate. Please bring your own water. There is no entrance fee.', 'When is the garden open?', [('Sunday morning','A'),('Saturday afternoon','B'),('Every evening','C'),('Monday morning','D')], 'A', 'Thông báo ghi giờ mở cửa Chủ nhật từ 9 giờ đến 12 giờ.'),
            ('The community garden is open on Sunday from 9 a.m. to noon. Visitors can enter through the blue gate. Please bring your own water. There is no entrance fee.', 'What should visitors bring?', [('A blue key','A'),('Their own water','B'),('A ticket','C'),('A garden chair','D')], 'B', 'Thông báo đề nghị khách tự mang nước.')])

        self._quiz('Listening A1: Meeting a classmate', 'listening', 'Bài nghe hội thoại với giọng tổng hợp; có nút dùng giọng đọc thiết bị nếu file không phát được.', 'A1', [
            ('A: Hi, are you new to this class? B: Yes, my name is Anna. A: Nice to meet you, Anna. I am Minh. B: Nice to meet you too. The English lesson starts at nine, right? A: Yes, in Room 12.', 'What is B’s name?', [('Anna','A'),('Mai','B'),('Linh','C'),('Emma','D')], 'A', 'B tự giới thiệu tên là Anna.'),
            ('A: Hi, are you new to this class? B: Yes, my name is Anna. A: Nice to meet you, Anna. I am Minh. B: Nice to meet you too. The English lesson starts at nine, right? A: Yes, in Room 12.', 'Where is the English lesson?', [('Room 10','A'),('Room 12','B'),('Room 20','C'),('The library','D')], 'B', 'Minh cho biết lớp học ở Room 12.')])
        self._quiz('Listening A2: A delivery update', 'listening', 'Bài nghe thông báo với giọng tổng hợp; transcript mở được khi cần.', 'A2', [
            ('Hello, this is Green Market. Your order will arrive Friday afternoon, not Thursday. The driver will call you ten minutes before delivery. Please make sure someone is available to receive the package.', 'When will the order arrive?', [('Thursday morning','A'),('Thursday afternoon','B'),('Friday afternoon','C'),('Friday evening','D')], 'C', 'Đơn hàng sẽ đến vào chiều thứ Sáu.'),
            ('Hello, this is Green Market. Your order will arrive Friday afternoon, not Thursday. The driver will call you ten minutes before delivery. Please make sure someone is available to receive the package.', 'What will the driver do before delivery?', [('Send a letter','A'),('Call the customer','B'),('Cancel the order','C'),('Visit the market','D')], 'B', 'Tài xế sẽ gọi trước 10 phút.')])
        self._quiz('Listening A2: A campus workshop announcement', 'listening', 'Bài nghe thông báo hoạt động sinh viên với audio giọng tổng hợp.', 'A2', [
            ('Hi, this is the student office. The computer workshop has moved from Tuesday to Wednesday. It will start at 4:30 p.m. in Lab 3. Please register by email before Monday evening. You do not need to bring a laptop; the lab will provide one.', 'When will the workshop take place?', [('Tuesday at 4:30 p.m.','A'),('Wednesday at 4:30 p.m.','B'),('Wednesday morning','C'),('Monday evening','D')], 'B', 'Buổi workshop được chuyển sang thứ Tư và bắt đầu lúc 4:30 chiều.'),
            ('Hi, this is the student office. The computer workshop has moved from Tuesday to Wednesday. It will start at 4:30 p.m. in Lab 3. Please register by email before Monday evening. You do not need to bring a laptop; the lab will provide one.', 'How should students register?', [('By email before Monday evening','A'),('At Lab 3 on Tuesday','B'),('By bringing a laptop','C'),('By calling after the workshop','D')], 'A', 'Thông báo yêu cầu đăng ký qua email trước tối thứ Hai.')])
        self._quiz('Reading A1: Campus cafe hours', 'reading', 'Đọc thông báo ngắn về giờ mở cửa và dịch vụ trong khuôn viên trường.', 'A1', [
            ('CAMPUS CAFE\nThe café opens at 7:30 a.m. from Monday to Friday. Breakfast is served until 10 a.m. Sandwiches are available after 11 a.m. On Friday, the café closes at 3 p.m. for cleaning.', 'Until what time is breakfast served?', [('9 a.m.','A'),('10 a.m.','B'),('11 a.m.','C'),('3 p.m.','D')], 'B', 'Thông báo cho biết bữa sáng được phục vụ đến 10 giờ.'),
            ('CAMPUS CAFE\nThe café opens at 7:30 a.m. from Monday to Friday. Breakfast is served until 10 a.m. Sandwiches are available after 11 a.m. On Friday, the café closes at 3 p.m. for cleaning.', 'Why does the café close at 3 p.m. on Friday?', [('For a staff meeting','A'),('For cleaning','B'),('For a holiday','C'),('For a private event','D')], 'B', 'Thông báo nêu rõ quán đóng cửa để dọn dẹp.')])
        self._quiz('Reading A2: Returning a library book', 'reading', 'Đọc email và xác định hạn trả sách cùng cách gia hạn.', 'A2', [
            ('Subject: Library book reminder\nHello Mai, your book is due on Wednesday. You can renew it online before 6 p.m. on Tuesday if nobody else has reserved it. If you return it, please use the book box beside the library entrance after 5 p.m. Best, Library Desk.', 'When is the book due?', [('Monday','A'),('Tuesday','B'),('Wednesday','C'),('Thursday','D')], 'C', 'Email ghi sách đến hạn vào thứ Tư.'),
            ('Subject: Library book reminder\nHello Mai, your book is due on Wednesday. You can renew it online before 6 p.m. on Tuesday if nobody else has reserved it. If you return it, please use the book box beside the library entrance after 5 p.m. Best, Library Desk.', 'How can Mai renew the book?', [('By calling on Wednesday','A'),('Online before Tuesday at 6 p.m.','B'),('At the entrance after 5 p.m.','C'),('By asking another student','D')], 'B', 'Người đọc có thể gia hạn trực tuyến trước 6 giờ tối thứ Ba.')])
        self._quiz('Reading A2: Student career event', 'reading', 'Đọc thông báo sự kiện và tìm địa điểm cùng vật cần chuẩn bị.', 'A2', [
            ('CAREER DAY\nThe university career day will take place on Thursday, 14 November, in Hall A from 9 a.m. to noon. Students can meet local employers and attend a short interview workshop. Please bring a printed copy of your CV. Registration is free at the student office.', 'Where will career day take place?', [('In the main library','A'),('In Hall A','B'),('At the student office','C'),('In the computer lab','D')], 'B', 'Địa điểm được ghi là Hall A.'),
            ('CAREER DAY\nThe university career day will take place on Thursday, 14 November, in Hall A from 9 a.m. to noon. Students can meet local employers and attend a short interview workshop. Please bring a printed copy of your CV. Registration is free at the student office.', 'What should students bring?', [('A laptop','A'),('A student card','B'),('A printed CV','C'),('A course book','D')], 'C', 'Thông báo yêu cầu mang một bản CV in.')])
        self._quiz('Listening A1: Finding the language center', 'listening', 'Nghe hội thoại tại quầy thông tin với audio giọng tổng hợp.', 'A1', [
            ('A: Good morning. Can I help you? B: Yes, I am looking for the language center. A: It is across from the main library, next to the bank. B: Thank you. Is it open now? A: Yes, until five p.m.', 'Which building is the language center across from?', [('Beside the bank','A'),('Across from the main library','B'),('Inside the station','C'),('Behind the café','D')], 'B', 'Nhân viên nói trung tâm đối diện thư viện chính.'),
            ('A: Good morning. Can I help you? B: Yes, I am looking for the language center. A: It is across from the main library, next to the bank. B: Thank you. Is it open now? A: Yes, until five p.m.', 'Until what time is it open?', [('Four p.m.','A'),('Five p.m.','B'),('Six p.m.','C'),('Seven p.m.','D')], 'B', 'Trung tâm mở cửa đến 5 giờ chiều.')])
        self._quiz('Listening A2: A study group change', 'listening', 'Nghe cuộc gọi về thay đổi lịch học nhóm với audio giọng tổng hợp.', 'A2', [
            ('A: Hi, Mai. We cannot meet on Wednesday. Room 4 is being used for an exam. B: Could we meet Thursday at six p.m.? A: Yes. I will book the computer lab. Please bring your research notes. B: Sure. I will message everyone.', 'Why can’t the group meet on Wednesday?', [('The teacher is away','A'),('The room is being used for an exam','B'),('The library is closed','C'),('The group has no notes','D')], 'B', 'Phòng học được dùng cho kỳ thi vào thứ Tư.'),
            ('A: Hi, Mai. We cannot meet on Wednesday. Room 4 is being used for an exam. B: Could we meet Thursday at six p.m.? A: Yes. I will book the computer lab. Please bring your research notes. B: Sure. I will message everyone.', 'What should students bring?', [('Their research notes','A'),('A printed CV','B'),('A laptop charger','C'),('A library book','D')], 'A', 'Người nói yêu cầu mang ghi chú nghiên cứu.')])
        self._quiz('Listening A2: Campus shuttle update', 'listening', 'Nghe thông báo về cổng đón và giấy tờ cần xuất trình bằng audio giọng tổng hợp.', 'A2', [
            ('Attention students. The campus shuttle to the station will leave from Gate 2 today, not Gate 1. It departs at 5:20 p.m. The next shuttle is at 5:50. Please show your student card when you board.', 'Where will the shuttle leave from today?', [('Gate 1','A'),('Gate 2','B'),('The main library','C'),('The student office','D')], 'B', 'Thông báo đổi điểm đón sang Gate 2.'),
            ('Attention students. The campus shuttle to the station will leave from Gate 2 today, not Gate 1. It departs at 5:20 p.m. The next shuttle is at 5:50. Please show your student card when you board.', 'What should passengers show?', [('A bus ticket','A'),('A printed schedule','B'),('Their student card','C'),('A library card','D')], 'C', 'Hành khách cần xuất trình thẻ sinh viên khi lên xe.')])
        vocab_question_count = Question.objects.filter(content__topic='Vocabulary practice', content__is_published=True).count()
        self.stdout.write(self.style.SUCCESS(f'Loaded {len(words)} original A1–C1 flashcards, {vocab_question_count} vocabulary questions, and 24 Reading/Listening questions.'))

    def _vocabulary_quizzes(self, vocab):
        """Create one meaning-recall question for every starter flashcard, grouped by level."""
        # Keep source positions/chunk titles stable when an individual card is
        # held; never shift every following card into a different 20-item deck.
        cards = list(vocab.flashcards.order_by('cefr_level', 'order'))
        for level in ('A1', 'A2', 'B1', 'B2', 'C1'):
            level_cards = [card for card in cards if card.cefr_level == level]
            if not level_cards:
                continue
            meaning_pool = list(dict.fromkeys(card.meaning_vi for card in level_cards if card.is_available and card.meaning_vi.strip()))
            if len(meaning_pool) < 4:
                continue
            for batch_index, offset in enumerate(range(0, len(level_cards), 20), 1):
                batch = level_cards[offset:offset + 20]
                available_count = sum(card.is_available for card in batch)
                if not available_count:
                    continue
                title = f'Vocabulary {level}: Chọn nghĩa đúng · Bộ {batch_index:02d}'
                content = self._upsert_content(title, {
                    'description': f'{available_count} câu ôn nghĩa từ vựng {level}, được tạo từ các flashcard cùng mức.',
                    'exam_type': 'TOEIC', 'content_type': 'vocabulary', 'skill': 'vocabulary',
                    'topic': 'Vocabulary practice', 'cefr_level': level,
                    'difficulty': 1 if level in ('A1', 'A2') else 2,
                    'estimated_minutes': max(5, round(len(batch) * 0.35)),
                    'source_name': 'Tự biên soạn từ bộ flashcard starter',
                    'rights_note': 'Câu hỏi và phương án được tạo từ nghĩa tiếng Việt tự biên soạn trong bộ flashcard; CEFR chỉ là nhãn tham khảo.',
                    'is_published': True,
                }, 'Câu hỏi trắc nghiệm sinh trực tiếp từ từng thẻ; cần giáo viên kiểm tra nội dung từ và mức CEFR trước khi dùng như bài đánh giá chính thức.')
                if not content._seed_created:
                    continue
                for order, card in enumerate(batch, 1):
                    if not card.is_available:
                        continue
                    decoys = [meaning for meaning in meaning_pool if meaning != card.meaning_vi]
                    # Deterministic hash rotation gives varied, repeatable distractors.
                    decoys.sort(key=lambda meaning: (len(meaning), meaning.casefold()))
                    if len(decoys) < 3:
                        continue
                    start = (offset + order * 3) % len(decoys)
                    selected = [decoys[(start + n) % len(decoys)] for n in range(3)]
                    choices = [(meaning, False) for meaning in selected] + [(card.meaning_vi, True)]
                    shift = (offset + order * 7) % 4
                    choices = choices[shift:] + choices[:shift]
                    question, _ = Question.objects.update_or_create(content=content, order=order, defaults={
                        'prompt': f'“{card.term}” có nghĩa gần nhất là gì?',
                        'explanation': f'{card.term}: {card.meaning_vi}. Ví dụ: {card.example_en}',
                        'explanation_vi': f'{card.term} nghĩa là “{card.meaning_vi}”. Ví dụ: {card.example_en} — {card.example_vi}',
                    })
                    for index, (meaning, correct) in enumerate(choices):
                        label = 'ABCD'[index]
                        AnswerOption.objects.update_or_create(question=question, label=label, defaults={
                            'text': meaning, 'is_correct': correct,
                            'explanation_vi': 'Đúng, đây là nghĩa của từ cần ôn.' if correct else 'Thử đối chiếu lại mặt sau của flashcard.',
                        })
                content.questions.filter(order__gt=len(batch)).delete()

    def _quiz(self, title, kind, description, level, items):
        source_url = 'https://learnenglish.britishcouncil.org/free-resources/reading/a1' if kind == 'reading' and level == 'A1' else 'https://learnenglish.britishcouncil.org/free-resources/reading/a2' if kind == 'reading' else 'https://learnenglish.britishcouncil.org/free-resources/listening/a1' if level == 'A1' else 'https://learnenglish.britishcouncil.org/free-resources/listening/a2'
        # The link is a level/skill design reference only; our passages, scripts and questions are original.
        content = self._upsert_content(title, {'description': f'Bài nền tảng CEFR {level} tự biên soạn cho người học có mục tiêu TOEIC. Đây là bài luyện kỹ năng ngắn, không phải đề TOEIC/IELTS hoặc mock test chính thức. ' + description, 'exam_type': 'TOEIC', 'content_type': kind, 'skill': kind, 'topic': level, 'cefr_level': level, 'difficulty': 1 if level == 'A1' else 2, 'estimated_minutes': 5, 'source_name': 'Tự biên soạn; British Council LearnEnglish chỉ dùng tham chiếu cấp độ/kỹ năng', 'source_url': source_url, 'rights_note': 'Văn bản, câu hỏi và đáp án tự biên soạn; audio Listening tổng hợp bằng Flite. URL chỉ tham chiếu cấp độ/kỹ năng, không sao chép bài ETS/British Council.', 'is_published': True}, 'AI đã rà soát sơ bộ đáp án, ngữ pháp, độ tự nhiên và mức A1/A2; chưa được giảng viên/người dạy tiếng Anh duyệt hoặc pilot, không phải hiệu chuẩn CEFR.')
        if not content._seed_created:
            return
        for order, (text, prompt, choices, key, explanation) in enumerate(items, 1):
            fields = {'prompt': prompt, 'explanation': explanation, 'explanation_vi': explanation}
            if kind == 'reading':
                fields['passage'] = text
            else:
                fields.update({'audio_script': text, 'transcript': text, 'audio_url': f'/static/audio/{slugify(title)}.mp3'})
            question, _ = Question.objects.update_or_create(content=content, order=order, defaults=fields)
            for label, choice in zip('ABCD', choices):
                option_text, marker = choice
                AnswerOption.objects.update_or_create(question=question, label=label, defaults={'text': option_text, 'is_correct': label == key, 'explanation_vi': 'Đáp án đúng.' if label == key else 'Thông tin này không khớp với nội dung bài.'})
        content.questions.filter(order__gt=len(items)).delete()

    def _upsert_content(self, title, defaults, review_note):
        reviewer = 'AI language QA (chưa được giáo viên duyệt)'
        now = timezone.now()
        review_fields = {
            'review_status': 'language_checked',
            'reviewer': reviewer,
            'reviewed_at': now,
            'review_note': review_note,
            # AI/content refresh is not evidence that the external source was checked.
            'source_checked_on': None,
        }
        content, created = LearningContent.objects.get_or_create(
            title=title, defaults={**defaults, **review_fields},
        )
        content._seed_created = created
        if not created and getattr(self, '_preserve_existing', False):
            return content
        if not created:
            content_fields = {
                field: value for field, value in {**defaults, **review_fields}.items()
                if field != 'reviewed_at'
            }
            changed = [
                field for field, value in content_fields.items()
                if getattr(content, field) != value
            ]
            if changed or content.reviewed_at is None:
                # A seed refresh supersedes any human approval. Keep the record
                # explicitly provisional and make the AI review metadata current.
                for field, value in {**content_fields, 'reviewed_at': now}.items():
                    setattr(content, field, value)
                changed_fields = set(changed) | {'reviewed_at'}
                content.save(update_fields=[*changed_fields, 'updated_at'])
        return content
