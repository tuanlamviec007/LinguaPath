"""Content editors must take the parent lock before mutable grading rows."""
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib import admin
from django.db import connection, connections, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, skipUnlessDBFeature

from .admin import FlashcardAdmin, LearningContentAdmin, QuestionAdmin, lock_content_rows
from .models import AnswerOption, Flashcard, LearningContent, Question


def content(title):
    return LearningContent.objects.create(
        title=title, content_type='vocabulary', skill='vocabulary',
        review_status='language_checked', is_published=True,
    )


def request():
    result = RequestFactory().post('/admin/')
    result._messages = Mock()
    return result


class AdminParentLockOrderTests(TestCase):
    def setUp(self):
        # Moving from the higher ID catches locking old/new parents in form order.
        self.destination = content('Destination')
        self.source = content('Source')
        self.question = Question.objects.create(content=self.source, prompt='Original', explanation='Reason')
        self.option = AnswerOption.objects.create(question=self.question, label='A', text='Original answer', is_correct=True)

    def record_queries(self, callback):
        events = []

        def record(execute, sql, params, many, context):
            if sql.startswith('SELECT') and 'FROM "learning_learningcontent"' in sql:
                events.append(('parent', tuple(params)))
            elif sql.startswith(('UPDATE', 'DELETE', 'INSERT')) and any(
                f'"learning_{model}"' in sql for model in ('question', 'answeroption', 'flashcard')
            ):
                events.append(('child', sql))
            return execute(sql, params, many, context)

        with connection.execute_wrapper(record):
            callback()
        return events

    def assert_parent_before_child(self, events, parents):
        first_parent = next(index for index, event in enumerate(events) if event[0] == 'parent')
        first_child = next(index for index, event in enumerate(events) if event[0] == 'child')
        self.assertLess(first_parent, first_child)
        self.assertEqual(events[first_parent][1], tuple(sorted(parents)))

    def test_question_move_locks_both_parents_before_question_and_answer_writes(self):
        self.question.content = self.destination
        form = SimpleNamespace(instance=self.question, changed_data=['content'], save_m2m=Mock())
        model_admin = QuestionAdmin(Question, admin.site)
        req = request()

        def edit():
            model_admin.save_model(req, self.question, form, change=True)
            self.option.text = 'Edited answer'
            formset = SimpleNamespace(has_changed=lambda: True, save=lambda: self.option.save())
            model_admin.save_related(req, form, [formset], change=True)

        events = self.record_queries(edit)
        self.assert_parent_before_child(events, [self.source.pk, self.destination.pk])
        self.assertFalse(LearningContent.objects.filter(pk__in=[self.source.pk, self.destination.pk], is_published=True).exists())

    def test_answer_only_edit_locks_parent_before_inline_write(self):
        form = SimpleNamespace(instance=self.question, changed_data=[], save_m2m=Mock())
        self.option.text = 'Edited answer'
        formset = SimpleNamespace(has_changed=lambda: True, save=lambda: self.option.save())
        events = self.record_queries(lambda: QuestionAdmin(Question, admin.site).save_related(request(), form, [formset], change=True))
        self.assert_parent_before_child(events, [self.source.pk])

    def test_content_inline_edit_locks_parent_before_question_write(self):
        form = SimpleNamespace(instance=self.source, changed_data=[], save_m2m=Mock())
        self.question.prompt = 'Edited inline'
        formset = SimpleNamespace(has_changed=lambda: True, save=lambda: self.question.save())
        events = self.record_queries(lambda: LearningContentAdmin(LearningContent, admin.site).save_related(request(), form, [formset], change=True))
        self.assert_parent_before_child(events, [self.source.pk])

    def test_question_bulk_delete_locks_all_parents_before_cascade(self):
        other = Question.objects.create(content=self.destination, prompt='Other', explanation='Reason')
        events = self.record_queries(lambda: QuestionAdmin(Question, admin.site).delete_queryset(
            request(), Question.objects.filter(pk__in=[self.question.pk, other.pk]),
        ))
        self.assert_parent_before_child(events, [self.source.pk, self.destination.pk])
        self.assertFalse(Question.objects.filter(pk__in=[self.question.pk, other.pk]).exists())

    def test_content_delete_locks_parent_before_cascading_children(self):
        parent_id = self.source.pk
        events = self.record_queries(lambda: LearningContentAdmin(LearningContent, admin.site).delete_model(request(), self.source))
        self.assert_parent_before_child(events, [parent_id])

    def test_flashcard_move_and_delete_lock_parents_before_child_writes(self):
        card = Flashcard.objects.create(content=self.source, term='schedule', meaning_vi='lịch')
        card.content = self.destination
        model_admin = FlashcardAdmin(Flashcard, admin.site)
        events = self.record_queries(lambda: model_admin.save_model(request(), card, SimpleNamespace(changed_data=['content']), change=True))
        self.assert_parent_before_child(events, [self.source.pk, self.destination.pk])
        events = self.record_queries(lambda: model_admin.delete_model(request(), card))
        self.assert_parent_before_child(events, [self.destination.pk])


@skipUnlessDBFeature('has_select_for_update')
class AdminGradeSerializationTests(TransactionTestCase):
    def test_teacher_question_write_waits_for_grading_parent_lock(self):
        parent = content('Concurrent source')
        question = Question.objects.create(content=parent, prompt='Original', explanation='Reason')
        started, child_written = Event(), Event()
        failures = []

        def teacher_edit():
            connections.close_all()
            try:
                row = Question.objects.get(pk=question.pk)
                row.prompt = 'Edited by teacher'
                form = SimpleNamespace(instance=row, changed_data=['prompt'], save_m2m=Mock())
                model_admin = QuestionAdmin(Question, admin.site)

                def observe(execute, sql, params, many, context):
                    if sql.startswith('SELECT') and 'FROM "learning_learningcontent"' in sql:
                        started.set()
                    result = execute(sql, params, many, context)
                    if sql.startswith('UPDATE "learning_question"'):
                        child_written.set()
                    return result

                with transaction.atomic(), connection.execute_wrapper(observe):
                    req = request()
                    model_admin.save_model(req, row, form, change=True)
                    model_admin.save_related(req, form, [], change=True)
            except Exception as exc:
                failures.append(exc)
            finally:
                connections.close_all()

        thread = Thread(target=teacher_edit, daemon=True)
        with transaction.atomic():
            lock_content_rows([parent.pk])
            thread.start()
            self.assertTrue(started.wait(5))
            wrote_before_grading_finished = child_written.wait(0.3)
            self.assertEqual(Question.objects.get(pk=question.pk).prompt, 'Original')
        thread.join(5)
        self.assertFalse(thread.is_alive(), 'Teacher edit did not finish after grading released its lock')
        self.assertFalse(failures)
        self.assertFalse(wrote_before_grading_finished, 'Teacher mutated grading evidence before acquiring its parent lock')
        self.assertTrue(child_written.is_set())
        question.refresh_from_db()
        self.assertEqual(question.prompt, 'Edited by teacher')
