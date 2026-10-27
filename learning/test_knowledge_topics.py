from django.test import SimpleTestCase

from .tutor_knowledge import find_knowledge


class KnowledgeTopicTests(SimpleTestCase):
    def test_explicitly_excluded_topic_does_not_override_vocabulary_request(self):
        for query in (
            'Tôi không hỏi về câu bị động, chỉ muốn biết từ invoice có nghĩa là gì',
            'Explain invoice, not passive voice',
        ):
            with self.subTest(query=query):
                self.assertEqual(find_knowledge(query), [])

    def test_difficulty_and_positive_requests_still_find_topic(self):
        for query in ('I do not understand passive voice', 'Giải thích câu bị động',
                      'Not passive voice in this example? Please explain passive voice.'):
            with self.subTest(query=query):
                self.assertIn('passive', [row['source_id'] for row in find_knowledge(query)])
