from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from pathlib import Path
from unittest.mock import Mock, patch

from .models import AnswerOption, AttemptAnswer, ErrorNotebookEntry, Flashcard, FlashcardReview, LearningContent, PracticeAttempt, Question, UserFlashcardState
from .vocabulary_import import import_vocabulary_csv


class LearningFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='learner', password='test-password-123')
        self.content = LearningContent.objects.create(
            title='Reading test', exam_type='TOEIC', content_type='reading', skill='reading', review_status='language_checked', is_published=True,
        )
        self.question = Question.objects.create(content=self.content, prompt='What day?', explanation='Read the notice.')
        self.correct = AnswerOption.objects.create(question=self.question, label='A', text='Monday', is_correct=True)
        self.wrong = AnswerOption.objects.create(question=self.question, label='B', text='Tuesday', is_correct=False)

    def test_register_creates_profile_and_logs_in(self):
        response = self.client.post(reverse('register'), {
            'username': 'new-learner', 'password1': 'A-strong-password-447!', 'password2': 'A-strong-password-447!',
        })
        self.assertRedirects(response, reverse('learning_goal'))
        self.assertTrue(get_user_model().objects.get(username='new-learner').learner_profile)

    def test_learning_goal_form_validates_toeic_range_and_updates_plan_preferences(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('learning_goal'), {'current_cefr': 'A2', 'target_cefr': 'B2', 'target_score': 850, 'daily_minutes': 45, 'target_date': ''})
        self.assertRedirects(response, reverse('dashboard'))
        self.user.learner_profile.refresh_from_db()
        self.assertEqual((self.user.learner_profile.target_score, self.user.learner_profile.daily_minutes), (850, 45))
        self.assertEqual((self.user.learner_profile.current_cefr, self.user.learner_profile.target_cefr), ('A2', 'B2'))
        self.assertTrue(self.user.learner_profile.onboarding_complete)
        invalid = self.client.post(reverse('learning_goal'), {'current_cefr': 'B2', 'target_cefr': 'A2', 'target_score': 1200, 'daily_minutes': 300, 'target_date': ''})
        self.assertEqual(invalid.status_code, 200)
        self.user.learner_profile.refresh_from_db()
        self.assertEqual(self.user.learner_profile.target_score, 850)

    def test_dashboard_sends_new_user_to_goal_setup(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('learning_goal'))

    def test_placement_assessment_scores_levels_and_requires_explicit_apply(self):
        from planner.models import LearnerProfile
        profile = LearnerProfile.objects.create(user=self.user, exam_goal='TOEIC', current_cefr='A1', target_cefr='B1', onboarding_complete=True)
        vocab = LearningContent.objects.create(title='Placement words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        for level_index, level in enumerate(['A1', 'A2', 'B1', 'B2', 'C1']):
            for index in range(3):
                Flashcard.objects.create(content=vocab, term=f'{level.lower()}word{index}', cefr_level=level, meaning_vi=f'nghĩa {level_index}-{index}')
        self.client.force_login(self.user)
        page = self.client.get(reverse('learning:placement_test'))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context['questions']), 15)
        session = self.client.session
        post_data = {f'q_{index}': item['correct'] for index, item in enumerate(session['placement_questions'])}
        response = self.client.post(reverse('learning:placement_test'), post_data)
        self.assertRedirects(response, reverse('learning:placement_result'))
        result = self.client.get(reverse('learning:placement_result'))
        self.assertContains(result, 'Mức gợi ý: C1')
        profile.refresh_from_db()
        self.assertEqual(profile.current_cefr, 'A1')
        self.client.post(reverse('learning:apply_placement_result'))
        profile.refresh_from_db()
        self.assertEqual(profile.current_cefr, 'C1')
        self.assertEqual(profile.target_cefr, 'C1')

    def test_placement_assessment_waits_for_three_words_per_level(self):
        from planner.models import LearnerProfile
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        self.client.force_login(self.user)
        page = self.client.get(reverse('learning:placement_test'))
        self.assertContains(page, 'Chưa đủ học liệu')
        self.assertEqual(page.context['questions'], [])

    def test_placement_does_not_ask_the_same_lemma_at_multiple_levels(self):
        from planner.models import LearnerProfile
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        vocab = LearningContent.objects.create(title='Placement duplicate words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        for level_index, level in enumerate(['A1', 'A2', 'B1', 'B2', 'C1']):
            for index in range(3):
                Flashcard.objects.create(content=vocab, term=f'{level.lower()}word{index}', cefr_level=level, meaning_vi=f'meaning {level_index}-{index}')
        Flashcard.objects.create(content=vocab, term='samelemma', cefr_level='A2', meaning_vi='nghĩa A2')
        Flashcard.objects.create(content=vocab, term='samelemma', cefr_level='B1', meaning_vi='nghĩa B1')
        self.client.force_login(self.user)
        page = self.client.get(reverse('learning:placement_test'))
        asked = [question['term'].casefold() for question in page.context['questions']]
        self.assertEqual(len(asked), 15)
        self.assertEqual(len(asked), len(set(asked)))

    def test_placement_assessment_rejects_duplicate_meanings_without_enough_distractors(self):
        from planner.models import LearnerProfile
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        vocab = LearningContent.objects.create(title='Repeated meanings', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        for level in ['A1', 'A2', 'B1', 'B2', 'C1']:
            for index in range(3):
                Flashcard.objects.create(content=vocab, term=f'{level.lower()}word{index}', cefr_level=level, meaning_vi='same meaning')
        self.client.force_login(self.user)
        page = self.client.get(reverse('learning:placement_test'))
        self.assertContains(page, 'tối thiểu 4 nghĩa khác nhau')
        self.assertEqual(page.context['questions'], [])

    def test_practice_score_is_saved_and_explanations_show(self):
        self.client.force_login(self.user)
        self.client.post(reverse('learning:practice', args=[self.content.id]))
        attempt = PracticeAttempt.objects.get(user=self.user)
        take_page = self.client.get(reverse('learning:take_attempt', args=[attempt.id]))
        self.assertContains(take_page, 'What day?')
        response = self.client.post(reverse('learning:submit_attempt', args=[attempt.id]), {
            f'question_{self.question.id}': str(self.correct.id),
        })
        self.assertRedirects(response, reverse('learning:attempt_result', args=[attempt.id]))
        attempt.refresh_from_db()
        self.assertEqual((attempt.status, attempt.correct_count, attempt.question_count), ('submitted', 1, 1))
        result = self.client.get(reverse('learning:attempt_result', args=[attempt.id]))
        self.assertContains(result, '100')
        self.assertContains(result, 'Read the notice.')

    def test_script_based_listening_is_listed_and_play_button_is_rendered(self):
        from planner.models import LearnerProfile
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True, exam_goal='TOEIC')
        listening = LearningContent.objects.create(
            title='Original A1 listening', exam_type='TOEIC', content_type='listening', skill='listening',
            cefr_level='A1', review_status='language_checked', is_published=True,
        )
        question = Question.objects.create(
            content=listening, prompt='Where is the class?', audio_script='A: It is in Room 2.',
            transcript='A: It is in Room 2.', explanation='The speaker says Room 2.',
        )
        for label, text, correct in [('A', 'Room 2', True), ('B', 'Room 3', False)]:
            AnswerOption.objects.create(question=question, label=label, text=text, is_correct=correct)
        self.client.force_login(self.user)
        listing = self.client.get(reverse('learning:practice_list'))
        self.assertContains(listing, 'Original A1 listening')
        self.client.post(reverse('learning:practice', args=[listening.id]))
        attempt = PracticeAttempt.objects.get(user=self.user, content=listening)
        practice_page = self.client.get(reverse('learning:take_attempt', args=[attempt.id]))
        self.assertContains(practice_page, 'data-speak="A: It is in Room 2."')
        self.assertContains(practice_page, 'data-speech-status')
        self.assertContains(practice_page, 'Bản chép lời hỗ trợ luyện tập')

    def test_wrong_answer_is_saved_to_private_error_notebook_and_can_be_reviewed(self):
        self.client.force_login(self.user)
        self.client.post(reverse('learning:practice', args=[self.content.id]))
        attempt = PracticeAttempt.objects.get(user=self.user)
        self.client.post(reverse('learning:submit_attempt', args=[attempt.id]), {
            f'question_{self.question.id}': str(self.wrong.id),
        })
        entry = ErrorNotebookEntry.objects.get(answer__attempt=attempt)
        page = self.client.get(reverse('learning:mistake_notebook'))
        self.assertContains(page, 'Sổ lỗi cá nhân')
        self.assertContains(page, 'Đáp án đúng:')
        response = self.client.post(reverse('learning:update_mistake_entry', args=[entry.id]), {
            'category': 'detail', 'learner_note': 'Đọc nhầm ngày trong thông báo.', 'reviewed': 'yes',
        })
        self.assertRedirects(response, reverse('learning:mistake_notebook'))
        entry.refresh_from_db()
        self.assertEqual(entry.category, 'detail')
        self.assertEqual(entry.learner_note, 'Đọc nhầm ngày trong thông báo.')
        self.assertIsNotNone(entry.reviewed_at)

    def test_error_notebook_cannot_be_viewed_or_updated_by_another_user(self):
        self.client.force_login(self.user)
        attempt = PracticeAttempt.objects.create(user=self.user, content=self.content, status='submitted', question_count=1)
        answer = AttemptAnswer.objects.create(
            attempt=attempt, question=self.question, selected_option=self.wrong, is_correct=False,
        )
        entry = ErrorNotebookEntry.objects.create(answer=answer)
        other = get_user_model().objects.create_user(username='notebook-other', password='test-password-123')
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse('learning:update_mistake_entry', args=[entry.id]), {'category': 'other'}).status_code, 404)
        self.assertNotContains(self.client.get(reverse('learning:mistake_notebook')), 'What day?')

    def test_users_cannot_submit_or_view_another_users_attempt(self):
        other = get_user_model().objects.create_user(username='other', password='test-password-123')
        attempt = PracticeAttempt.objects.create(user=self.user, content=self.content, question_count=1)
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse('learning:submit_attempt', args=[attempt.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('learning:attempt_result', args=[attempt.id])).status_code, 404)

    def test_option_from_another_question_cannot_score_as_correct(self):
        other_question = Question.objects.create(content=self.content, prompt='Other question?', explanation='No.')
        foreign_correct = AnswerOption.objects.create(question=other_question, label='A', text='Foreign', is_correct=True)
        attempt = PracticeAttempt.objects.create(user=self.user, content=self.content, question_count=1)
        self.client.force_login(self.user)
        self.client.post(reverse('learning:submit_attempt', args=[attempt.id]), {f'question_{self.question.id}': str(foreign_correct.id)})
        attempt.refresh_from_db()
        self.assertEqual(attempt.correct_count, 0)

    def test_getting_start_page_does_not_create_attempt_and_other_exam_is_blocked(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('learning:practice', args=[self.content.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PracticeAttempt.objects.count(), 0)
        self.content.exam_type = 'IELTS'
        self.content.save(update_fields=['exam_type'])
        self.assertEqual(self.client.get(reverse('learning:practice', args=[self.content.id])).status_code, 404)

    def test_published_content_reports_missing_or_ambiguous_answer_key(self):
        self.content.review_status = 'language_checked'
        self.question.options.all().delete()
        self.assertEqual(self.content.publication_issues(), ['Câu 1: cần ít nhất hai phương án.', 'Câu 1: cần đúng một phương án đúng.'])

    def test_content_publication_flags_mismatched_skill_taxonomy(self):
        self.content.skill = 'listening'
        self.assertIn('Kỹ năng phải khớp với loại nội dung.', self.content.publication_issues())

    def test_vocabulary_quiz_can_pass_publication_checks_without_flashcards(self):
        quiz = LearningContent.objects.create(
            title='Vocabulary quiz', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary',
            topic='Vocabulary practice', source_name='Tự biên soạn', rights_note='Nội dung gốc.',
            review_status='language_checked', is_published=True,
        )
        question = Question.objects.create(content=quiz, prompt='What does “arrive” mean?', explanation_vi='Nghĩa là đến nơi.')
        for label, text, correct in [('A', 'đến nơi', True), ('B', 'rời đi', False), ('C', 'ngồi xuống', False), ('D', 'đợi chờ', False)]:
            AnswerOption.objects.create(question=question, label=label, text=text, is_correct=correct)
        self.assertEqual(quiz.publication_issues(), [])


class FlashcardReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='reviewer', password='test-password-123')
        content = LearningContent.objects.create(title='Words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        self.card = Flashcard.objects.create(content=content, term='schedule', meaning_vi='lịch trình')
        self.client.force_login(self.user)

    def test_review_rating_creates_spaced_review(self):
        response = self.client.post(reverse('learning:review_flashcard', args=[self.card.id]), {'rating': 'known'})
        self.assertRedirects(response, reverse('learning:flashcards_content', args=[self.card.content_id]) + '?level=A1')
        review = FlashcardReview.objects.get(user=self.user, flashcard=self.card)
        self.assertEqual(review.rating, 'known')
        self.assertGreater(review.due_at, review.reviewed_at)

    def test_again_rating_schedules_a_short_relearning_step(self):
        self.client.post(reverse('learning:review_flashcard', args=[self.card.id]), {'rating': 'again'})
        state = self.user.flashcard_states.get(flashcard=self.card)
        self.assertAlmostEqual((state.due_at - timezone.now()).total_seconds(), 600, delta=3)
        self.assertEqual(self.client.get(reverse('learning:flashcards')).context['card_count'], 0)
        with patch('learning.views.timezone.now', return_value=state.due_at + timedelta(seconds=1)):
            self.assertEqual(self.client.get(reverse('learning:flashcards')).context['card_count'], 1)

    def test_flashcard_page_has_flip_faces_pronunciation_and_recall_actions(self):
        page = self.client.get(reverse('learning:flashcards'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'href="/static/css/app.css"')
        self.assertContains(page, 'src="/static/js/app.js"')
        self.assertContains(page, 'data-flip')
        self.assertContains(page, 'flash-front')
        self.assertContains(page, 'flash-back')
        self.assertContains(page, 'data-speak="schedule"')
        self.assertContains(page, 'Chưa nhớ')

    def test_flashcard_page_can_search_term_or_meaning_and_filter_topic(self):
        Flashcard.objects.create(content=self.card.content, term='campus', meaning_vi='khuôn viên trường', topic='Study')
        response = self.client.get(reverse('learning:flashcards'), {'q': 'khuôn viên', 'topic': 'Study'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cards'].paginator.count, 1)
        self.assertContains(response, 'campus')

    def test_full_vocabulary_view_can_show_already_scheduled_cards(self):
        UserFlashcardState.objects.create(
            user=self.user, flashcard=self.card, last_rating='known',
            reviewed_at=timezone.now(), due_at=timezone.now() + timedelta(days=2), review_count=1,
        )
        due_view = self.client.get(reverse('learning:flashcards'))
        all_view = self.client.get(reverse('learning:flashcards'), {'all': '1'})
        self.assertEqual(due_view.context['cards'].paginator.count, 0)
        self.assertEqual(all_view.context['cards'].paginator.count, 1)


class SeededLearningMaterialTests(TestCase):
    def test_starter_seed_has_expanded_idempotent_vocabulary_and_practice(self):
        call_command('seed_starter_content', verbosity=0)
        call_command('seed_starter_content', verbosity=0)
        vocab = LearningContent.objects.get(title='Ngân hàng từ vựng A1–C1: Học tập và đời sống')
        self.assertEqual(vocab.flashcards.count(), 1000)
        self.assertEqual(vocab.questions.count(), 0)
        vocabulary_questions = Question.objects.filter(content__is_published=True, content__topic='Vocabulary practice')
        self.assertEqual(vocabulary_questions.count(), 1000)
        self.assertEqual(Question.objects.filter(content__is_published=True).count(), 1024)
        self.assertEqual(vocab.flashcards.values('term').distinct().count(), 1000)
        self.assertEqual(set(vocab.flashcards.values_list('cefr_level', flat=True)), {'A1', 'A2', 'B1', 'B2', 'C1'})
        listening = Question.objects.filter(content__content_type='listening', content__is_published=True)
        self.assertEqual(listening.count(), 12)
        self.assertTrue(all(question.audio_script for question in listening))
        audio_urls = {question.audio_url for question in listening}
        self.assertEqual(len(audio_urls), 6)
        for audio_url in audio_urls:
            self.assertTrue(audio_url.startswith('/static/audio/'))
            self.assertTrue((Path('static') / audio_url.removeprefix('/static/')).is_file())
        for question in Question.objects.filter(content__is_published=True):
            self.assertEqual(question.options.count(), 4)
            self.assertEqual(question.options.filter(is_correct=True).count(), 1)
        for level in ('A1', 'A2', 'B1', 'B2', 'C1'):
            self.assertEqual(vocabulary_questions.filter(content__cefr_level=level).count(), vocab.flashcards.filter(cefr_level=level).count())

    def test_expanding_seed_preserves_existing_flashcard_review_state(self):
        user = get_user_model().objects.create_user(username='legacy-reviewer', password='test-password-123')
        old = LearningContent.objects.create(
            title='Nền tảng A1–A2: Từ vựng cho học tập và đời sống', exam_type='TOEIC',
            content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True,
        )
        old_card = Flashcard.objects.create(content=old, term='address', meaning_vi='địa chỉ', cefr_level='A1')
        state = UserFlashcardState.objects.create(
            user=user, flashcard=old_card, last_rating='known',
            reviewed_at=timezone.now(), due_at=timezone.now() + timedelta(days=1), review_count=2,
        )
        call_command('seed_starter_content', verbosity=0)
        migrated = LearningContent.objects.get(title='Ngân hàng từ vựng A1–C1: Học tập và đời sống')
        self.assertEqual(migrated.flashcards.count(), 1000)
        self.assertEqual(migrated.flashcards.get(term='address').id, old_card.id)
        state.refresh_from_db()
        self.assertEqual(state.flashcard_id, old_card.id)
        self.assertFalse(LearningContent.objects.filter(title=old.title).exists())

    def test_vocabulary_csv_import_requires_provenance_and_keeps_content_draft(self):
        csv_text = 'term,meaning_vi,cefr_level,example_en\nreliable,đáng tin cậy,B1,The supplier is reliable.\n'
        content, created, updated = import_vocabulary_csv(
            csv_text, title='CSV B1 vocabulary', topic='Work', source_name='Tự biên soạn',
            source_url='', rights_note='Nội dung do nhóm tự viết.',
        )
        card = content.flashcards.get(term='reliable')
        self.assertEqual((created, updated), (1, 0))
        self.assertEqual(card.cefr_level, 'B1')
        self.assertEqual(card.source_name, 'Tự biên soạn')
        self.assertFalse(content.is_published)

    def test_vocabulary_csv_rejects_invalid_level_or_missing_provenance(self):
        with self.assertRaises(ValueError):
            import_vocabulary_csv(
                'term,meaning_vi,cefr_level\nword,từ,C2\n', title='Bad', source_name='Nguồn',
                rights_note='Được phép sử dụng.',
            )
        with self.assertRaises(ValueError):
            import_vocabulary_csv(
                'term,meaning_vi,cefr_level\nword,từ,A1\n', title='Bad', source_name='',
                rights_note='',
            )


class TutorRetrievalTests(TestCase):
    def setUp(self):
        self.content = LearningContent.objects.create(title='Cartridge schedule', exam_type='TOEIC', content_type='reading', skill='reading', review_status='language_checked', is_published=True)
        self.question = Question.objects.create(content=self.content, prompt='When will cartridges arrive?', passage='The cartridges arrive on Thursday.', explanation='The notice says Thursday.', explanation_vi='Thông báo nói hộp mực đến vào thứ Năm.')
        self.user = get_user_model().objects.create_user(username='tutor-learner', password='secure-test-password')
        attempt = PracticeAttempt.objects.create(user=self.user, content=self.content, status='submitted', question_ids=[self.question.id], question_count=1, submitted_at=timezone.now())
        AttemptAnswer.objects.create(attempt=attempt, question=self.question)

    def test_retrieval_returns_only_published_relevant_lesson(self):
        from .ai import answer_tutor_question
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            result = answer_tutor_question('When do cartridges arrive?', user=self.user)
        self.assertEqual(result['mode'], 'retrieval_only')
        self.assertIn('Thursday', result['answer'])
        self.assertEqual(result['sources'], ['Cartridge schedule'])

    def test_unrelated_query_does_not_reach_llm_or_receive_unrelated_source(self):
        from .ai import answer_tutor_question
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            result = answer_tutor_question('How do galaxies form?')
        self.assertEqual(result['mode'], 'no_match')
        self.assertEqual(result['sources'], [])

    def test_question_id_uses_exact_published_question_context(self):
        from .ai import retrieve_learning_context
        evidence = retrieve_learning_context('Please explain option B for this question', question_id=self.question.id, user=self.user)
        self.assertEqual(evidence[0]['source'], 'Cartridge schedule')
        self.assertIn('Thursday', evidence[0]['text'])

    def test_llm_receives_limited_lesson_context_and_returns_source(self):
        from . import ai
        AnswerOption.objects.create(question=self.question, label='A', text='Thursday', is_correct=True,
                                    explanation_vi='Thông báo nêu thứ Năm.')
        AnswerOption.objects.create(question=self.question, label='B', text='Friday',
                                    explanation_vi='Thông báo không nêu thứ Sáu.')
        mock_client = Mock()
        mock_client.responses.create.return_value.output_text = 'Đoạn văn nêu rõ thời gian là thứ Năm.'
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(ai, 'OpenAI', Mock(return_value=mock_client)):
            result = ai.answer_tutor_question('When do cartridges arrive?', user=self.user, use_ai=True)
        self.assertEqual(result['mode'], 'llm_rag')
        self.assertEqual(result['sources'], ['Cartridge schedule'])
        self.assertIn('Thursday', mock_client.responses.create.call_args.kwargs['input'])

    def test_authenticated_learning_pages_render(self):
        user = get_user_model().objects.create_user(username='page-test', password='secure-password')
        from planner.models import LearnerProfile
        LearnerProfile.objects.create(user=user, onboarding_complete=True)
        self.client.force_login(user)
        urls = [
            reverse('dashboard'), reverse('learning_goal'), reverse('learning:flashcards'),
            reverse('learning:practice_list'), reverse('learning:mistake_notebook'), reverse('progress'), reverse('tutor'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
