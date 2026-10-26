from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from planner.models import LearnerProfile
from .gamification import get_learning_rewards
from .models import Flashcard, FlashcardReview, LearningContent, SavedWord, UserFlashcardState, VocabularyQuizSession


class SavedWordsJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='wordbook-user')
        cls.other = get_user_model().objects.create_user(username='wordbook-other')
        for user in (cls.user, cls.other):
            LearnerProfile.objects.create(user=user, exam_goal='TOEIC', onboarding_complete=True)
        cls.content = LearningContent.objects.create(title='Published vocabulary', content_type='vocabulary', skill='vocabulary', exam_type='TOEIC', is_published=True, review_status='teacher_approved')
        terms = [('umbrella', 'ô dù'), ('cloud', 'đám mây'), ('ticket', 'vé tàu'), ('bank', 'ngân hàng'), ('baggage', 'hành lý'), ('passenger', 'hành khách'), ('printer', 'máy in'), ('currency', 'tiền tệ')]
        cls.cards = [Flashcard.objects.create(content=cls.content, term=term, meaning_vi=meaning, cefr_level='B1' if i < 5 else 'B2', topic='Travel' if i < 5 else 'Work', example_en=f'This example uses {term}.') for i,(term,meaning) in enumerate(terms)]

    def setUp(self):
        self.client.force_login(self.user)

    def act(self, card, action='save', **kwargs):
        return self.client.post(reverse('learning:save_word', args=[card.pk]), {'action': action, **kwargs}, HTTP_ACCEPT='application/json')

    def test_save_remove_are_idempotent_private_and_do_not_award_learning_credit(self):
        card = self.cards[0]
        for _ in range(2):
            result = self.act(card)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()['saved'])
        self.assertEqual(SavedWord.objects.filter(user=self.user).count(), 1)
        self.assertEqual(get_learning_rewards(self.user)['total_xp'], 0)
        self.assertFalse(FlashcardReview.objects.exists())
        self.assertFalse(UserFlashcardState.objects.exists())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('learning:saved_words')).context['saved_count'], 0)
        self.act(card, 'remove')
        self.assertTrue(SavedWord.objects.filter(user=self.user, flashcard=card).exists())
        self.client.force_login(self.user)
        for _ in range(2):
            self.assertFalse(self.act(card, 'remove').json()['saved'])
        self.assertFalse(SavedWord.objects.exists())

    def test_post_auth_csrf_and_action_validation(self):
        url = reverse('learning:save_word', args=[self.cards[0].pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'action':'toggle'}).status_code, 400)
        self.assertEqual(self.client.post(url, {'action':['save','remove']}).status_code, 400)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.user)
        self.assertEqual(guarded.post(url, {'action':'save'}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(url, {'action':'save'}).status_code, 302)
        self.assertFalse(SavedWord.objects.exists())

    def test_safe_redirect_and_non_javascript_form(self):
        url = reverse('learning:save_word', args=[self.cards[0].pk])
        for target in ('https://example.test/','//example.test/','/\\example.test/'):
            self.assertRedirects(self.client.post(url, {'action':'save','next':target}), reverse('learning:saved_words'))
        target = reverse('learning:flashcards') + '?all=1&level=B1'
        self.assertRedirects(self.client.post(url, {'action':'remove','next':target}), target)

    def test_list_filters_pagination_and_source_visibility(self):
        for card in self.cards:
            self.act(card)
        page = self.client.get(reverse('learning:saved_words'), {'q':'ticket','level':'B1','topic':'Travel'})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['filtered_count'], 1)
        self.assertContains(page, 'ticket')
        self.assertEqual(page.context['saved_count'], 8)
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        self.assertEqual(self.client.get(reverse('learning:saved_words')).context['saved_count'], 0)
        self.assertEqual(self.act(self.cards[0]).status_code, 404)
        self.assertEqual(self.act(self.cards[0], 'remove').status_code, 200)
        self.assertEqual(SavedWord.objects.filter(user=self.user).count(), 7)

    def test_teacher_drafts_and_other_exam_never_enter_saved_bank(self):
        for changes in ({'review_status':'draft'}, {'exam_type':'IELTS'}):
            values = {'title':'Unavailable', 'content_type':'vocabulary', 'skill':'vocabulary', 'is_published':True, 'review_status':'teacher_approved'}
            values.update(changes)
            content = LearningContent.objects.create(**values)
            card = Flashcard.objects.create(content=content, term='private-word', meaning_vi='nghĩa ẩn')
            self.assertEqual(self.act(card).status_code, 404)

    def test_saved_quiz_is_scoped_to_own_words_and_retains_snapshot_after_removal(self):
        for card in self.cards[:5]:
            self.act(card)
        SavedWord.objects.create(user=self.other, flashcard=self.cards[-1])
        response = self.client.post(reverse('learning:quiz_start'), {'source':'saved','count':'5'})
        quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertRedirects(response, reverse('learning:quiz_take', args=[quiz.pk]))
        self.assertEqual(quiz.vocabulary_source, 'saved')
        self.assertEqual({q['card_id'] for q in quiz.snapshot}, {c.pk for c in self.cards[:5]})
        for card in self.cards[:5]:
            self.act(card, 'remove')
        self.assertEqual(self.client.get(reverse('learning:quiz_take', args=[quiz.pk])).status_code, 200)
        self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), {f'answer_{q["number"]}':q['correct_key'] for q in quiz.snapshot})
        quiz.refresh_from_db()
        self.assertEqual(quiz.correct_count, 5)
        result = self.client.get(reverse('learning:quiz_result', args=[quiz.pk]))
        self.assertTrue(all(item['can_save'] and not item['is_saved'] for item in result.context['results']))

    def test_too_few_saved_words_never_falls_back_to_public_questions(self):
        for card in self.cards[:4]:
            self.act(card)
        result = self.client.post(reverse('learning:quiz_start'), {'source':'saved','count':'5'})
        self.assertRedirects(result, reverse('learning:quiz_hub')+'?source=saved')
        self.assertFalse(VocabularyQuizSession.objects.exists())
        self.assertEqual(self.client.post(reverse('learning:quiz_start'), {'source':'other','count':'5'}).status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('learning:quiz_hub'), {'source':'saved'}).context['available_count'], 0)

    def test_saved_flags_render_on_flashcards_result_and_dashboard(self):
        self.act(self.cards[0])
        page = self.client.get(reverse('learning:flashcards'), {'all':'1'})
        states = {c.pk:c.is_saved for c in page.context['cards']}
        self.assertTrue(states[self.cards[0].pk])
        self.assertFalse(states[self.cards[1].pk])
        self.assertContains(page, 'data-save-word')
        self.assertEqual(self.client.get(reverse('dashboard')).context['saved_word_count'], 1)

    def test_twenty_per_page_and_stable_recent_order(self):
        for i in range(23):
            card = Flashcard.objects.create(content=self.content, term=f'extra-{i}', meaning_vi=f'nghĩa {i}')
            SavedWord.objects.create(user=self.user, flashcard=card)
        page1 = self.client.get(reverse('learning:saved_words')).context['cards']
        page2 = self.client.get(reverse('learning:saved_words'), {'page':2}).context['cards']
        self.assertEqual((len(page1), len(page2)), (20,3))
        self.assertFalse({c.pk for c in page1} & {c.pk for c in page2})

    def test_result_does_not_offer_to_bookmark_a_different_revised_source_word(self):
        self.client.post(reverse('learning:quiz_start'), {'count':'5'})
        quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), {f'answer_{q["number"]}':q['correct_key'] for q in quiz.snapshot})
        original = quiz.snapshot[0]
        Flashcard.objects.filter(pk=original['card_id']).update(term='a revised term')
        rows = self.client.get(reverse('learning:quiz_result', args=[quiz.pk])).context['results']
        row = next(item for item in rows if item['card_id'] == original['card_id'])
        self.assertEqual(row['term'], original['term'])
        self.assertFalse(row['can_save'])
