"""Validation of original bilingual vocabulary; no Cambridge content is fetched."""
import csv
import re
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / 'data' / 'vocabulary_3000' / 'selected_2000.csv'
COLUMNS = ('term', 'cefr_level', 'part_of_speech', 'meaning_vi', 'example_en', 'example_vi', 'topic', 'cloze_answer', 'distractor_1', 'distractor_2', 'distractor_3')
LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1')
CHAPTERS = {
    'Đời sống và ẩm thực': {'Clothing', 'Food', 'Home', 'Kitchen'},
    'Du lịch và tự nhiên': {'Animals', 'Geography', 'Nature', 'Places', 'Plants', 'Sport', 'Transport', 'Travel', 'Weather'},
    'Học tập và văn hóa': {'Art', 'Cinema', 'Culture', 'Education', 'Language', 'Literature', 'Media', 'Music', 'Performing arts', 'Student life'},
    'Công việc và dịch vụ': {'Business', 'Civic life', 'Finance', 'Jobs', 'Law', 'Office', 'Services', 'Shopping', 'Work'},
    'Khoa học và sức khỏe': {'Biology', 'Body', 'Chemistry', 'Computing', 'Cybersecurity', 'Energy', 'Health', 'Materials', 'Mathematics', 'Measurement', 'Media technology', 'Nutrition', 'Physics', 'Science', 'Technology'},
    'Hành động và diễn đạt': {'Actions', 'Certainty', 'Communication', 'Descriptions', 'Feelings', 'Frequency', 'Manner', 'Place', 'Quantity', 'Study', 'Time'},
}


def chapter_for_topic(topic):
    return next((chapter for chapter, topics in CHAPTERS.items() if topic in topics), topic)


def balanced_batches(rows, maximum=20):
    if not rows:
        return
    count = (len(rows) + maximum - 1) // maximum
    size, extra = divmod(len(rows), count)
    offset = 0
    for index in range(count):
        length = size + (index < extra)
        yield rows[offset:offset + length]
        offset += length


def normalize_term(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def answer_pattern(answer):
    return re.compile(r'(?<![\w])' + re.escape(answer) + r'(?![\w])', re.IGNORECASE)


def validate_rows(rows, expected_count=None):
    cleaned, terms, examples = [], set(), set()
    for number, raw in enumerate(rows, 2):
        if set(raw) != set(COLUMNS) or any(not isinstance(raw.get(key), str) for key in COLUMNS):
            raise ValueError(f'Dòng {number}: sai số cột hoặc kiểu dữ liệu.')
        row = {key: raw[key].strip() for key in COLUMNS}
        if any(not value for value in row.values()):
            raise ValueError(f'Dòng {number}: thiếu dữ liệu.')
        if row['cefr_level'] not in LEVELS:
            raise ValueError(f'Dòng {number}: CEFR không hợp lệ.')
        for key, limit in {'term': 120, 'meaning_vi': 240, 'part_of_speech': 40, 'topic': 80, 'cloze_answer': 120}.items():
            if len(row[key]) > limit:
                raise ValueError(f'Dòng {number}: {key} quá dài.')
        if any('<' in value or '>' in value or '\n' in value for value in row.values()):
            raise ValueError(f'Dòng {number}: không chấp nhận HTML hoặc xuống dòng trong trường.')
        term = normalize_term(row['term'])
        if term in terms:
            raise ValueError(f'Dòng {number}: trùng từ {term}.')
        example = normalize_term(row['example_en'])
        if example in examples:
            raise ValueError(f'Dòng {number}: trùng câu ví dụ.')
        if not 5 <= len(row['example_en'].split()) <= 35:
            raise ValueError(f'Dòng {number}: câu ví dụ quá ngắn hoặc quá dài.')
        if len(answer_pattern(row['cloze_answer']).findall(row['example_en'])) != 1:
            raise ValueError(f'Dòng {number}: từ điền phải xuất hiện đúng một lần trong câu.')
        answers = [row['cloze_answer'], *(row[f'distractor_{i}'] for i in range(1, 4))]
        if len({normalize_term(answer) for answer in answers}) != 4:
            raise ValueError(f'Dòng {number}: bốn lựa chọn phải khác nhau.')
        terms.add(term)
        examples.add(example)
        cleaned.append(row)
    if expected_count is not None and len(cleaned) != expected_count:
        raise ValueError(f'Cần {expected_count} mục từ, hiện có {len(cleaned)}.')
    return cleaned


def load_catalog(path=None, expected_count=2000):
    with Path(path or CATALOG_PATH).open(encoding='utf-8-sig', newline='') as stream:
        return validate_rows(list(csv.DictReader(stream)), expected_count)


def cloze_sentence(row):
    return answer_pattern(row['cloze_answer']).sub('_____', row['example_en'], count=1)
