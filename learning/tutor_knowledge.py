"""Small, original reference notes. Editorial draft; no teacher certification."""
import re
import unicodedata


KNOWLEDGE = [
    {
        'id': 'despite-although', 'title': 'Despite và although',
        'triggers': ('despite', 'although', 'in spite of'),
        'text': 'Despite / in spite of + danh từ, cụm danh từ hoặc V-ing. Although + mệnh đề có chủ ngữ và động từ.\n'
                'Ví dụ: Despite the rain, the delivery arrived on time. → Mặc dù trời mưa, đơn hàng vẫn đến đúng giờ.\n'
                'Although it was raining, the delivery arrived on time. → Mặc dù trời đang mưa, đơn hàng vẫn đến đúng giờ.\n'
                'Không dùng “despite of”. Có thể dùng “despite the fact that + mệnh đề”. Trong văn viết chuẩn, tránh dùng although và but để nối cùng một quan hệ nhượng bộ.\n'
                'Áp dụng: ___ the delay, the team finished the report. A. Although B. Despite. Chọn B vì “the delay” là cụm danh từ.',
    },
    {
        'id': 'responsible-for', 'title': 'Be responsible for',
        'triggers': ('responsible',),
        'text': 'Be responsible for + danh từ / V-ing: chịu trách nhiệm về việc gì.\n'
                'The manager is responsible for hiring new employees. → Người quản lý chịu trách nhiệm tuyển nhân viên mới.\n'
                'Với “responsible ___ hiring”, chọn for; “at”, “on”, “with” không tạo cấu trúc phù hợp trong câu này.\n'
                'Responsible to + người/cấp quản lý có nghĩa chịu trách nhiệm trước người đó; đây là quan hệ khác với responsible for + nhiệm vụ.',
    },
    {
        'id': 'subject-verb', 'title': 'Hòa hợp chủ ngữ và động từ',
        'triggers': ('subject verb', 'subject-verb', 'hoa hop chu ngu', 'chu ngu va dong tu'),
        'text': 'Ở hiện tại đơn, chủ ngữ ngôi thứ ba số ít thường đi với động từ thêm -s/-es; chủ ngữ số nhiều dùng dạng cơ bản.\n'
                'The list of available rooms is on the desk. → Danh sách phòng còn trống nằm trên bàn. Chủ ngữ chính là “the list”, không phải “rooms”.\n'
                'Khi làm câu điền động từ, xác định cụm chủ ngữ chính trước, sau đó kiểm tra thì và thể. Không chỉ nhìn danh từ đứng gần chỗ trống nhất.',
    },
    {
        'id': 'present-perfect', 'title': 'Hiện tại hoàn thành',
        'triggers': ('present perfect', 'hien tai hoan thanh', 'since va for'),
        'text': 'Hiện tại hoàn thành: have/has + quá khứ phân từ, thường diễn tả trải nghiệm, kết quả liên quan hiện tại hoặc trạng thái kéo dài tới hiện tại.\n'
                'She has worked here for three years. → Cô ấy đã làm việc ở đây được ba năm (và hiện vẫn làm).\n'
                'For + khoảng thời gian; since + mốc bắt đầu. “Yesterday” hoặc một thời điểm quá khứ đã kết thúc thường đi với quá khứ đơn. Dấu hiệu thời gian chỉ là gợi ý; cần đọc nghĩa cả câu.',
    },
    {
        'id': 'passive', 'title': 'Câu bị động',
        'triggers': ('passive voice', 'cau bi dong', 'the bi dong'),
        'text': 'Cấu trúc bị động cơ bản: be (chia theo thì) + quá khứ phân từ. Chủ ngữ nhận tác động của hành động.\n'
                'The invoices were sent yesterday. → Các hóa đơn đã được gửi hôm qua.\n'
                '“Invoices” không tự gửi chính nó nên cần bị động; “yesterday” đặt sự việc ở quá khứ. Với động từ khuyết thiếu: modal + be + quá khứ phân từ, như “must be signed”.',
    },
    {
        'id': 'word-forms', 'title': 'Chọn từ loại trong câu điền từ',
        'triggers': ('word form', 'word forms', 'chon tu loai', 'dang tu'),
        'text': 'Đọc cấu trúc quanh chỗ trống để xác định chức năng cần có, sau đó kiểm tra nghĩa và kết hợp từ. Hậu tố chỉ là gợi ý, có ngoại lệ.\n'
                'The team completed the project successfully. → Nhóm đã hoàn thành dự án một cách thành công. “Successfully” là trạng từ bổ nghĩa cho cách hoàn thành.\n'
                'So sánh: a successful project (tính từ trước danh từ), the success of the project (danh từ), the team succeeded (động từ).',
    },
    {
        'id': 'listening-strategy', 'title': 'Cách luyện Listening',
        'triggers': ('listening', 'luyen nghe', 'chien thuat nghe'),
        'text': 'Khi luyện nghe, làm lần đầu trong điều kiện không xem lời thoại. Đọc yêu cầu và phương án khi phần hướng dẫn cho phép, dự đoán bối cảnh và thông tin cần tìm.\n'
                'Sau khi nộp: đối chiếu lời thoại, xác định đoạn chứa bằng chứng và cách diễn đạt tương đương. Nghe lại câu bị bỏ lỡ, rồi luyện nhắc lại một đoạn ngắn.\n'
                'Đừng chọn một phương án chỉ vì nó lặp lại từ bạn vừa nghe. Luyện phát âm/nhắc lại hỗ trợ học, nhưng không phải phần chấm nói của TOEIC Listening & Reading.',
    },
    {
        'id': 'reading-strategy', 'title': 'Cách luyện Reading',
        'triggers': ('reading', 'luyen doc', 'chien thuat doc'),
        'text': 'Khi luyện đọc hiểu, xác định loại câu hỏi: thông tin cụ thể, mục đích, suy luận hay diễn đạt tương đương. Đọc lướt để nắm người viết, người nhận và bối cảnh, rồi quay lại tìm bằng chứng.\n'
                'Với câu hỏi chi tiết, kiểm tra thông tin trong văn bản thay vì dùng hiểu biết ngoài bài. Với nhiều văn bản, có thể cần kết hợp thông tin giữa các đoạn.\n'
                'Sau khi nộp, ghi lại vì sao bạn chọn sai: bỏ sót phủ định, nhầm người, nhầm thời gian hoặc hiểu sai cách diễn đạt.',
    },
]


def normalize(value):
    value = unicodedata.normalize('NFKD', value.lower().replace('đ', 'd'))
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).split())


def find_knowledge(query):
    from .tutor_provenance import knowledge_source_ref

    normalized = normalize(query)
    # Quoted headwords plus an explicit definition request belong to vocabulary
    # lookup, even when the headword is the name of a skill or grammar note.
    quoted = re.search(r'["“”‘’\']([^"“”‘’\']+)["“”‘’\']', normalized)
    vocab_intent = re.search(r'\b(?:word|term|define|meaning|translate|tu|nghia|dich)\b', normalized)
    if quoted and vocab_intent:
        return []
    matches = []
    for note in KNOWLEDGE:
        # Ignore explicitly excluded topics, while retaining questions such as
        # 'I do not understand passive voice' that still ask about that topic.
        def requested(trigger):
            pattern = r'(?<!\w)' + re.escape(trigger) + r'(?!\w)'
            for match in re.finditer(pattern, normalized):
                prefix = normalized[:match.start()]
                if not re.search(r'(?:\bnot\s+|\brather than\s+|\bkhong (?:hoi|noi|ban) (?:ve )?|\bkhong phai )$', prefix):
                    return True
            return False

        if any(requested(trigger) for trigger in note['triggers']):
            if note['id'] in ('reading-strategy', 'listening-strategy') and not re.search(
                r'\b(?:learn|learning|practice|practise|improve|train|study|prepare|strategy|strategies|tips|luyen|chien thuat|cach|hoc|ky nang)\b', normalized
            ):
                continue
            matches.append({
                'source': note['title'], 'text': note['text'], 'kind': 'knowledge',
                'source_id': note['id'], 'source_ref': knowledge_source_ref(note['id'], note),
                'href': '/tutor/#knowledge-' + note['id'], 'review_status': 'language_checked',
            })
    return matches
