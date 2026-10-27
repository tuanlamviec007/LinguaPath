from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import Flashcard, LearningContent, UserFlashcardState


class WorkspaceFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='workspace-owner')
        LearnerProfile.objects.create(user=cls.user, onboarding_complete=True)
        cls.decks = [LearningContent.objects.create(
            title=f'Office deck {i}', content_type='vocabulary', skill='vocabulary',
            is_published=True, review_status='language_checked',
        ) for i in range(2)]
        cls.cards = [Flashcard.objects.create(
            content=cls.decks[i % 2], term=f'word{i:02}', meaning_vi=f'nghĩa {i}',
            cefr_level='A1', topic='Work', order=i,
        ) for i in range(25)]

    def setUp(self):
        self.client.force_login(self.user)


class FlashcardWorkspaceTests(WorkspaceFixture):
    def test_scriptless_cards_offer_meaning_and_record_rating(self):
        page = self.client.get(reverse('learning:flashcards'), {'topic': 'Work'})
        card = list(page.context['cards'])[0]
        fallback = page.content.decode().split('<noscript>', 1)[1].split('</noscript>', 1)[0]
        self.assertIn('<details', fallback)
        self.assertIn(card.term, fallback)
        self.assertIn(card.meaning_vi, fallback)
        self.assertIn('name="csrfmiddlewaretoken"', fallback)
        self.assertIn(reverse('learning:review_flashcard', args=[card.pk]), fallback)
        response = self.client.post(reverse('learning:review_flashcard', args=[card.pk]),
                                    {'rating': 'hard', 'next': card.rating_return_url})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(card.reviews.filter(user=self.user, rating='hard').exists())

    def test_library_rating_keeps_cross_deck_filters_page_and_position(self):
        page = self.client.get(reverse('learning:flashcards'), {
            'all': 1, 'level': 'A1', 'topic': 'Work', 'q': 'word', 'page': 2,
        })
        card = list(page.context['cards'])[0]
        target = card.rating_return_url
        self.assertContains(page, 'name="next"')
        self.assertContains(page, f'id="flashcard-{card.pk}"')
        response = self.client.post(reverse('learning:review_flashcard', args=[card.pk]), {'rating':'hard','next':target})
        self.assertEqual(response.status_code, 302)
        parsed = urlsplit(response.url)
        self.assertEqual(parsed.path, reverse('learning:flashcards'))
        self.assertEqual(parse_qs(parsed.query), {'all':['1'],'level':['A1'],'topic':['Work'],'q':['word'],'page':['2']})
        self.assertEqual(parsed.fragment, f'flashcard-{card.pk}')
        restored = self.client.get(response.url)
        self.assertEqual(restored.context['page_obj'].number, 2)
        self.assertEqual(len(restored.context['cards']), 5)

    def test_due_rating_continues_to_another_card_without_changing_workspace(self):
        page = self.client.get(reverse('learning:flashcards'), {'topic':'Work'})
        cards = list(page.context['cards'])
        card, following = cards[:2]
        response = self.client.post(reverse('learning:review_flashcard',args=[card.pk]), {'rating':'known','next':card.rating_return_url})
        self.assertEqual(urlsplit(response.url).fragment, f'flashcard-{following.pk}')
        restored = self.client.get(response.url)
        self.assertNotIn(card.pk, [item.pk for item in restored.context['cards']])
        self.assertContains(restored, f'id="flashcard-{following.pk}"')
        self.assertFalse(restored.context['show_all'])

    def test_early_known_guard_also_preserves_valid_return_context(self):
        card=self.cards[0]
        UserFlashcardState.objects.create(user=self.user, flashcard=card, last_rating='known',
            reviewed_at=timezone.now(), due_at=timezone.now()+timedelta(days=3), interval_days=3)
        target=reverse('learning:flashcards')+'?all=1&topic=Work#flashcard-'+str(card.pk)
        response=self.client.post(reverse('learning:review_flashcard',args=[card.pk]),{'rating':'known','next':target})
        self.assertEqual(response.url,target)
        self.assertFalse(card.reviews.exists())

    def test_redirect_rejects_external_and_nonworkspace_destinations(self):
        card=self.cards[0]
        fallback=reverse('learning:flashcards_content',args=[card.content_id])+'?level=A1'
        for target in ('https://evil.invalid/', '//evil.invalid/', '/admin/', '/learn/quiz/', '/%2f%2fevil.invalid/', '/\\evil.invalid/'):
            with self.subTest(target=target):
                response=self.client.post(reverse('learning:review_flashcard',args=[card.pk]),{'rating':'hard','next':target})
                self.assertEqual(response.url,fallback)
        response=self.client.post(reverse('learning:review_flashcard',args=[card.pk]),{
            'rating':'hard','next':reverse('learning:flashcards')+'?all=1&token=discard&level=Z9&page=999999999#bad',
        })
        self.assertEqual(response.url,reverse('learning:flashcards')+'?all=1')


class PrivateWorkspaceResponseTests(WorkspaceFixture):
    def test_personal_html_and_redirects_are_private_and_not_stored(self):
        for route in ('dashboard','progress','learning_goal','learning:flashcards','learning:quiz_hub','learning:practice_list','learning:mistake_notebook','learning:saved_words'):
            with self.subTest(route=route):
                response=self.client.get(reverse(route))
                self.assertEqual(response.status_code,200)
                self.assertIn('private',response['Cache-Control'])
                self.assertIn('no-store',response['Cache-Control'])
                self.assertIn('Cookie',response['Vary'])
        response=self.client.post(reverse('learning:review_flashcard',args=[self.cards[0].pk]), {'rating':'hard'})
        self.assertIn('no-store',response['Cache-Control'])

    def test_json_error_and_login_required_redirect_cannot_be_stored(self):
        response=self.client.post(reverse('learning:save_word',args=[self.cards[0].pk]), {'action':'invalid'},HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code,400)
        self.assertIn('no-store',response['Cache-Control'])
        self.client.logout()
        response=self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code,302)
        self.assertIn('no-store',response['Cache-Control'])

    def test_anonymous_auth_form_is_not_stored_and_public_home_stays_public(self):
        self.client.logout()
        for route in ('login','register','password_reset'):
            response=self.client.get(reverse(route))
            self.assertEqual(response.status_code, 503 if route == 'password_reset' else 200)
            self.assertIn('no-store',response['Cache-Control'])
        home=self.client.get(reverse('home'))
        self.assertEqual(home.status_code,200)
        self.assertNotIn('no-store',home.get('Cache-Control',''))
