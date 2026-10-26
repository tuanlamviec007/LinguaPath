"""Answer rules shared by grading, drafts and the quiz mistake queue."""
import unicodedata
import re

MAX_RECALL_LENGTH = 240


def normalize_recall_answer(value):
    if not isinstance(value, str):
        return ''
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().replace('’', "'").replace('‘', "'").split())


def quiz_answer_is_valid(question, answer, mode='meaning'):
    if not isinstance(answer, str):
        return False
    if mode == 'recall':
        return bool(normalize_recall_answer(answer)) and len(answer) <= MAX_RECALL_LENGTH and not any(
            unicodedata.category(char) == 'Cc' and not char.isspace() for char in answer
        )
    options = question.get('options')
    if not isinstance(options, list):
        return False
    return answer in {option.get('key') for option in options if isinstance(option, dict) and isinstance(option.get('key'), str)}


def quiz_answer_is_correct(question, answer, mode='meaning'):
    if not quiz_answer_is_valid(question, answer, mode):
        return False
    if mode == 'recall':
        target = normalize_recall_answer(question.get('term'))
        return bool(target) and normalize_recall_answer(answer) == target
    return answer == question.get('correct_key')


def recall_hint(question):
    term = normalize_recall_answer(question.get('term'))
    count = len(term.split())
    initial = term[0] if len(term) >= 3 and term[0].isalpha() else ''
    return (f'Bắt đầu bằng “{initial}” · ' if initial else '') + f'{count} từ'


def recall_prompt_signature(question):
    """Everything that can distinguish a typed prompt, excluding CEFR metadata.

    A mixed-level quiz does not tell the learner which lemma a shared meaning
    intends. Only the displayed definition, POS and actual hint distinguish it.
    """
    return (normalize_recall_answer(question.get('meaning_vi')),
            normalize_recall_answer(question.get('part_of_speech')),
            recall_hint(question))


def recall_prompt_is_usable(question):
    """A definition that already names the English answer is not a recall task."""
    target = normalize_recall_answer(question.get('term'))
    prompt = normalize_recall_answer(question.get('meaning_vi'))
    return bool(target and prompt) and re.search(r'(?<!\w)' + re.escape(target) + r'(?!\w)', prompt) is None
