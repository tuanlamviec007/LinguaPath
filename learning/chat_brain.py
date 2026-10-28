"""Conversational chat routing; RAG is a tool, not a prerequisite for every reply."""
import re
import unicodedata
from .ai import answer_tutor_question, _keep_capacity_for_web, _result
from .ai_limits import reserve_tutor_call
from .ai_provider import generate_cloudflare_answer, provider_name, tutor_ai_available


def intent_of(query):
    text = ''.join(c for c in unicodedata.normalize('NFD', query.lower()) if unicodedata.category(c) != 'Mn').replace('đ', 'd')
    text = re.sub(r'\b(?:ko|khong|hong|k)\b', 'khong', text)
    if re.search(r'khong (?:con )?(?:muon|thich) hoc|chan (?:hoc|qua)|nan (?:qua|chi)|met (?:qua|moi)|mat dong luc|hoc (?:mai )?khong (?:vao|nho)|bo cuoc', text):
        return 'motivation'
    if re.fullmatch(r'\s*(?:chao(?: ban| lumi)?|xin chao(?: lumi)?|hello(?: lumi)?|hi(?: lumi)?|lumi oi)[!.,\s]*', text):
        return 'greeting'
    if re.fullmatch(r'\s*(?:cam on(?: ban| lumi)?|thank(?:s| you)(?: lumi)?)[!.,\s]*', text):
        return 'thanks'
    return 'learning'


def basic_reply(intent, history=(), notice=''):
    previous = any(message.get('role') == 'user' and intent_of(message.get('content', '')) == intent for message in history)
    if intent == 'motivation':
        answer = ('Mình nghe bạn. Hôm nay bạn không cần ép mình học tiếp đâu. Bạn muốn nghỉ một chút, hay kể mình nghe điều làm bạn chán nhất: bài khó, học mãi chưa nhớ, hay bạn đang mệt?'
                  if not previous else 'Ừ, mình không ép bạn học tiếp. Mình có thể ở đây nghe bạn nói thôi. Điều gì đang làm bạn thấy nặng nhất lúc này?')
    elif intent == 'greeting':
        answer = 'Chào bạn, mình là Lumi! Hôm nay bạn muốn hỏi một điều về tiếng Anh, tìm cách học nhẹ hơn, hay chỉ trò chuyện một chút?'
    elif intent == 'thanks':
        answer = 'Không có gì nhé. Khi nào muốn hỏi tiếp hoặc cần mình giải thích theo cách khác, cứ nói với mình.'
    else:
        answer = 'Mình có thể trò chuyện về cách học và giải thích tiếng Anh, kể cả khi kho học liệu chưa có bài khớp. Hiện mình đang ở chế độ trả lời cơ bản; bật “Trò chuyện bằng AI” để mình giải thích linh hoạt hơn. Bạn cũng có thể nêu một từ hoặc cấu trúc để mình tra cứu trực tiếp.'
    return _result({'answer': answer + notice, 'mode': 'conversation', 'chat_intent': intent, 'sources': [], 'evidence_sources': []})


@_keep_capacity_for_web
def general_reply(query, *, user, use_ai, chat_history=(), intent='learning'):
    if not use_ai or not tutor_ai_available() or provider_name() != 'cloudflare':
        return basic_reply(intent, chat_history)
    allowed, reason = reserve_tutor_call(user)
    if not allowed:
        return basic_reply(intent, chat_history, '\n\nLượt AI hiện chưa khả dụng. Mình vẫn có thể đồng hành và giúp bạn tra cứu học liệu.')
    try:
        result = generate_cloudflare_answer(query,
            'Hội thoại hỗ trợ học tập và kiến thức tiếng Anh tổng quát. Lượt này không có nguồn học liệu truy xuất; không giả trích dẫn hoặc tuyên bố đã tra cứu.',
            task='chat', history=chat_history, include_metadata=True)
        answer = _result({'answer': result['answer'], 'mode': 'llm_chat', 'chat_intent': intent,
                        'sources': [], 'evidence_sources': []}, provider='cloudflare', model=result.get('model'))
        answer['generation']['bridge_prompt_version'] = result.get('prompt_version')
        return answer
    except Exception:
        return basic_reply(intent, chat_history, '\n\nKết nối AI đang gián đoạn nên mình đang trả lời cơ bản.')


def answer_chat_question(query, *, user, use_ai=False, chat_history=None, **options):
    intent = intent_of(query)
    history = chat_history or []
    if intent != 'learning':
        return general_reply(query, user=user, use_ai=use_ai, chat_history=history, intent=intent)
    result = answer_tutor_question(query, user=user, use_ai=use_ai, chat_history=history, **options)
    if result['mode'] == 'no_match':
        return general_reply(query, user=user, use_ai=use_ai, chat_history=history, intent=intent)
    return result
