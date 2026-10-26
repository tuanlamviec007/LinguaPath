from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch

from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .management.commands.repair_starter_trip import OLD_MATCH, PARENT_MATCH, REPAIRED_VALUES
from .management.commands.seed_starter_content import load_expanded_rows
from .models import Flashcard, LearningContent, Question
from .locking import nonkey_row_lock
from .vocabulary_import import import_vocabulary_csv


CSV = 'term,meaning_vi,cefr_level\nreliable,đáng tin cậy,B1\n'
META = dict(title='Imported set', source_name='Original author', rights_note='Original content.')


class ImportSourceValidationTests(TestCase):
    def test_malformed_csv_never_partially_writes_or_invalidates_review(self):
        parent = LearningContent.objects.create(
            title=META['title'], content_type='vocabulary', skill='vocabulary',
            is_published=True, review_status='language_checked', reviewer='Original reviewer',
        )
        card = Flashcard.objects.create(content=parent, term='reliable', meaning_vi='giữ nguyên')
        invalid_sources = [
            'term,term,meaning_vi,cefr_level\nx,y,từ,A1\n',
            'term,meaning_vi,cefr_level,unknown\nx,từ,A1,ignored\n',
            CSV + 'second,từ,A1,unexpected\n',
            CSV + 'second,từ\n',
            CSV + 'second,từ,C2\n',
            CSV + ' RELIABLE ,từ,B1\n',
            CSV + '"unfinished,từ,A1\n',
            'term,meaning_vi\nx,từ\n',
            'term,,meaning_vi,cefr_level\nx,ignored,từ,A1\n',
        ]
        for text in invalid_sources:
            with self.subTest(text=text), CaptureQueriesContext(connection) as queries:
                with self.assertRaises(ValueError):
                    import_vocabulary_csv(text, **META)
            self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')) for q in queries))
            parent.refresh_from_db()
            card.refresh_from_db()
            self.assertTrue(parent.is_published)
            self.assertEqual(parent.reviewer, 'Original reviewer')
            self.assertEqual(card.meaning_vi, 'giữ nguyên')
            self.assertEqual(Flashcard.objects.count(), 1)

    def test_lengths_and_http_urls_are_validated_before_writes(self):
        invalid = [
            ('term,meaning_vi,cefr_level\n' + 'x' * 121 + ',từ,A1\n', {}),
            ('term,meaning_vi,cefr_level,topic\nx,từ,A1,' + 'x' * 81 + '\n', {}),
            ('term,meaning_vi,cefr_level,audio_url\nx,từ,A1,https://\n', {}),
            ('term,meaning_vi,cefr_level,audio_url\nx,từ,A1,ftp://example.test/a.mp3\n', {}),
            (CSV, {'title': 'x' * 181}),
            (CSV, {'source_url': 'https://'}),
            (CSV, {'rights_note': 'x' * 241}),
            (CSV, {'exam_type': 'OTHER'}),
        ]
        for text, changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                import_vocabulary_csv(text, **{**META, **changes})
        self.assertFalse(LearningContent.objects.exists())
        self.assertFalse(Flashcard.objects.exists())

    def test_valid_quoted_csv_and_normalized_merge_preserve_omitted_editor_fields(self):
        parent, _, _ = import_vocabulary_csv(CSV, **META)
        card = parent.flashcards.get()
        card.example_en = 'A teacher wrote this example.'
        card.audio_url = 'https://example.test/teacher.mp3'
        card.save()
        text = 'term,meaning_vi,cefr_level\n RELIABLE ,"đáng tin cậy, ổn định",b1\n'
        imported, created, updated = import_vocabulary_csv(text, **META)
        card.refresh_from_db()
        self.assertEqual((created, updated), (0, 1))
        self.assertEqual(imported.pk, parent.pk)
        self.assertEqual(card.meaning_vi, 'đáng tin cậy, ổn định')
        self.assertEqual(card.example_en, 'A teacher wrote this example.')
        self.assertEqual(card.audio_url, 'https://example.test/teacher.mp3')
        self.assertEqual(card.term, 'reliable')

    def test_permission_callback_observes_actual_parent_inside_transaction(self):
        seen = []
        def check(parent):
            self.assertTrue(connection.in_atomic_block)
            seen.append(None if parent is None else parent.pk)
        parent, _, _ = import_vocabulary_csv(CSV, permission_check=check, **META)
        import_vocabulary_csv(CSV, permission_check=check, **META)
        self.assertEqual(seen, [None, parent.pk])

    def test_ambiguous_existing_parent_is_rejected_without_overwrite(self):
        for _ in range(2):
            LearningContent.objects.create(title=META['title'], content_type='vocabulary', skill='vocabulary')
        with self.assertRaises(ValueError):
            import_vocabulary_csv(CSV, **META)
        self.assertFalse(Flashcard.objects.exists())


class AdminImportPermissionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='csv-staff', is_staff=True)
        self.client.force_login(self.user)
        self.url = reverse('admin:learning_flashcard_import_csv')

    def grant(self, *codenames):
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label='learning', codename__in=codenames))

    def post(self):
        return self.client.post(self.url, {
            **META, 'csv_file': SimpleUploadedFile('words.csv', CSV.encode(), content_type='text/csv'),
        })

    def test_parent_add_change_permission_matrix_matches_actual_operation(self):
        flash_perms = ['add_flashcard', 'change_flashcard']
        for exists in (False, True):
            for can_add, can_change in ((False, False), (True, False), (False, True), (True, True)):
                with self.subTest(exists=exists, can_add=can_add, can_change=can_change):
                    Flashcard.objects.all().delete()
                    LearningContent.objects.all().delete()
                    parent = None
                    if exists:
                        parent = LearningContent.objects.create(
                            title=META['title'], content_type='vocabulary', skill='vocabulary',
                            is_published=True, review_status='language_checked', reviewer='Keep reviewer',
                        )
                        Flashcard.objects.create(content=parent, term='original', meaning_vi='giữ nguyên')
                    self.grant(*flash_perms,
                               *(['add_learningcontent'] if can_add else []),
                               *(['change_learningcontent'] if can_change else []))
                    allowed = can_change if exists else can_add
                    response = self.post()
                    self.assertEqual(response.status_code, 302 if allowed else 403)
                    if not allowed:
                        self.assertEqual(LearningContent.objects.count(), int(exists))
                        self.assertEqual(Flashcard.objects.count(), int(exists))
                        if parent:
                            parent.refresh_from_db()
                            self.assertTrue(parent.is_published)
                            self.assertEqual(parent.reviewer, 'Keep reviewer')

    def test_flashcard_permissions_are_still_required(self):
        self.grant('add_learningcontent', 'change_learningcontent', 'add_flashcard')
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(LearningContent.objects.exists())

    def test_existing_parent_object_permission_is_honored(self):
        parent = LearningContent.objects.create(title=META['title'], content_type='vocabulary', skill='vocabulary')
        self.grant('add_flashcard', 'change_flashcard', 'add_learningcontent', 'change_learningcontent')
        parent_admin = admin.site._registry[LearningContent]
        with patch.object(parent_admin, 'has_change_permission', return_value=False) as permission:
            self.assertEqual(self.post().status_code, 403)
        self.assertEqual(permission.call_args.args[1].pk, parent.pk)
        self.assertFalse(Flashcard.objects.exists())

    def test_race_to_existing_parent_rechecks_change_permission_and_rolls_back(self):
        # Simulate the title having been created after the upload/page was
        # prepared: the submitted request still carries only add permission.
        self.grant('add_flashcard', 'change_flashcard', 'add_learningcontent')
        parent = LearningContent.objects.create(
            title=META['title'], content_type='vocabulary', skill='vocabulary', reviewer='Preserved',
        )
        self.assertEqual(self.post().status_code, 403)
        parent.refresh_from_db()
        self.assertEqual(parent.reviewer, 'Preserved')
        self.assertFalse(Flashcard.objects.exists())

    def test_import_takes_same_owner_lock_before_mutex_parent_and_child_writes(self):
        parent = LearningContent.objects.create(title=META['title'], content_type='vocabulary', skill='vocabulary')
        self.grant('add_flashcard', 'change_flashcard', 'change_learningcontent')
        events = []
        user_table = get_user_model()._meta.db_table

        def observe(execute, sql, params, many, context):
            if sql.startswith('SELECT') and f'FROM "{user_table}"' in sql:
                events.append(('owner', tuple(params), sql))
            elif sql.startswith('SELECT') and 'FROM "django_content_type"' in sql:
                events.append(('mutex', tuple(params), sql))
            elif sql.startswith('SELECT') and 'FROM "learning_learningcontent"' in sql:
                events.append(('parent', tuple(params), sql))
            elif sql.startswith(('UPDATE', 'INSERT', 'DELETE')) and '"learning_flashcard"' in sql:
                events.append(('child', tuple(params), sql))
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observe):
            self.assertEqual(self.post().status_code, 302)
        owner_positions = [i for i, event in enumerate(events) if event[0] == 'owner']
        mutex = next(i for i, event in enumerate(events) if event[0] == 'mutex')
        parent_lock = next(i for i, event in enumerate(events) if event[0] == 'parent')
        child = next(i for i, event in enumerate(events) if event[0] == 'child')
        self.assertLess(max(owner_positions), mutex)
        self.assertIn(self.user.pk, events[max(owner_positions)][1])
        self.assertLess(mutex, parent_lock)
        self.assertLess(parent_lock, child)
        self.assertIn(parent.pk, events[child][1])
        if connection.features.has_select_for_no_key_update:
            self.assertIn('FOR NO KEY UPDATE', events[max(owner_positions)][2])
            self.assertIn('FOR NO KEY UPDATE', events[mutex][2])


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentImportAuthorizationTests(TransactionTestCase):
    def test_add_only_second_import_waits_then_requires_change_permission(self):
        first_checked, release_first = Event(), Event()
        second_lock_requested, second_checked = Event(), Event()
        results, failures = [], []

        def import_as_add_only(first):
            connections.close_all()
            try:
                def authorize(parent):
                    if first:
                        self.assertIsNone(parent)
                        first_checked.set()
                        if not release_first.wait(5):
                            raise AssertionError('Timed out waiting to release first import')
                    else:
                        second_checked.set()
                    if parent is not None:
                        raise PermissionDenied

                def observe(execute, sql, params, many, context):
                    if not first and sql.startswith('SELECT') and 'django_content_type' in sql:
                        second_lock_requested.set()
                    return execute(sql, params, many, context)

                with connections['default'].execute_wrapper(observe):
                    import_vocabulary_csv(CSV, **META, permission_check=authorize)
                results.append('created')
            except PermissionDenied:
                results.append('denied')
            except Exception as exc:
                failures.append(exc)
            finally:
                connections.close_all()

        threads = [Thread(target=import_as_add_only, args=(first,)) for first in (True, False)]
        try:
            threads[0].start()
            self.assertTrue(first_checked.wait(5))
            threads[1].start()
            self.assertTrue(second_lock_requested.wait(5))
            self.assertFalse(second_checked.wait(0.1))
        finally:
            release_first.set()
            for thread in threads:
                if thread.ident is not None:
                    thread.join(6)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(failures)
        self.assertCountEqual(results, ['created', 'denied'])
        self.assertEqual(LearningContent.objects.count(), 1)
        self.assertEqual(Flashcard.objects.count(), 1)


@skipUnlessDBFeature('has_select_for_no_key_update')
class ImportAdminLogFKCompatibilityTests(TransactionTestCase):
    def test_admin_log_fk_checks_commit_while_actor_and_contenttype_mutex_are_held(self):
        user = get_user_model().objects.create_user(username='import-log-actor', is_staff=True)
        content_type = ContentType.objects.get(app_label='learning', model='learningcontent')
        writer_started, writer_finished, committed = Event(), Event(), Event()
        failures = []

        def write_admin_log():
            connections.close_all()
            try:
                with transaction.atomic():
                    # A regression to FOR UPDATE must fail promptly even when
                    # PostgreSQL checks these deferred FKs at transaction exit.
                    with connections['default'].cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '2s'")
                    writer_started.set()
                    LogEntry.objects.create(
                        user_id=user.pk, content_type_id=content_type.pk,
                        object_id='1', object_repr='Import FK compatibility probe',
                        action_flag=CHANGE, change_message='',
                    )
                committed.set()
            except Exception as exc:
                failures.append(exc)
            finally:
                writer_finished.set()
                connections.close_all()

        writer = Thread(target=write_admin_log)
        try:
            with transaction.atomic():
                nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
                nonkey_row_lock(ContentType.objects.all()).get(pk=content_type.pk)
                writer.start()
                self.assertTrue(writer_started.wait(5))
                self.assertTrue(writer_finished.wait(5))
                # This assertion runs before either mutex is released. A
                # deferred FK check must have committed, not merely inserted.
                self.assertTrue(committed.is_set(), failures)
                self.assertFalse(failures)
        finally:
            if writer.ident is not None:
                writer.join(6)
        self.assertFalse(writer.is_alive())
        self.assertEqual(LogEntry.objects.filter(user=user, content_type=content_type).count(), 1)


class StarterSourcePreservationTests(TestCase):
    def test_fixed_source_has_full_trip_translation_and_real_topic(self):
        trip = next(row for row in load_expanded_rows() if row['term'] == 'trip')
        self.assertEqual(trip['example_vi'], REPAIRED_VALUES['example_vi'])
        self.assertEqual(trip['topic'], 'Travel')

    def test_malformed_starter_source_fails_before_any_parent_write(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.csv'
            path.write_text('term,cefr_level,part_of_speech,meaning_vi,example_en,example_vi,topic\n'
                            'trip,B1,noun,chuyến đi,English example,Cuối tuần trước, phần sau,Travel\n')
            with patch('learning.management.commands.seed_starter_content.EXPANDED_PATH', path):
                with CaptureQueriesContext(connection) as queries, self.assertRaises(CommandError):
                    call_command('seed_starter_content', stdout=StringIO())
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')) for q in queries))
        self.assertFalse(LearningContent.objects.exists())

    def test_seed_rerun_keeps_editor_parent_card_question_and_added_records(self):
        call_command('seed_starter_content', stdout=StringIO())
        parent = LearningContent.objects.get(title='Ngân hàng từ vựng A1–C1: Học tập và đời sống')
        card = parent.flashcards.get(term='trip')
        card.term = 'TRIP'
        card.example_vi = 'Bản dịch giáo viên đã sửa.'
        card.source_name = 'Teacher source'
        card.save()
        parent.description = 'Teacher description'
        parent.reviewer = 'Human reviewer metadata'
        parent.save()
        exercise = LearningContent.objects.filter(topic='Vocabulary practice').first()
        question = exercise.questions.first()
        question.prompt = 'Teacher question'
        question.save()
        extra = Question.objects.create(content=exercise, order=999, prompt='Teacher added question')
        snapshot = (parent.updated_at, parent.reviewed_at, parent.review_status, parent.is_published)
        call_command('seed_starter_content', stdout=StringIO())
        parent.refresh_from_db()
        card.refresh_from_db()
        question.refresh_from_db()
        self.assertEqual(parent.description, 'Teacher description')
        self.assertEqual(parent.reviewer, 'Human reviewer metadata')
        self.assertEqual((parent.updated_at, parent.reviewed_at, parent.review_status, parent.is_published), snapshot)
        self.assertEqual(card.example_vi, 'Bản dịch giáo viên đã sửa.')
        self.assertEqual(card.source_name, 'Teacher source')
        self.assertEqual(parent.flashcards.filter(term__iexact='trip').count(), 1)
        self.assertEqual(question.prompt, 'Teacher question')
        self.assertTrue(Question.objects.filter(pk=extra.pk).exists())


class KnownTripRepairTests(TestCase):
    def make_old(self, **changes):
        parent = LearningContent.objects.create(
            **PARENT_MATCH, skill='vocabulary', is_published=True,
            review_status='language_checked', reviewer='Old QA', reviewed_at=timezone.now(),
        )
        return Flashcard.objects.create(content=parent, **{**OLD_MATCH, **changes})

    def test_default_and_dry_run_leave_all_values_unchanged(self):
        card = self.make_old()
        for flags in ({}, {'dry_run': True}):
            output = StringIO()
            call_command('repair_starter_trip', stdout=output, **flags)
            card.refresh_from_db()
            card.content.refresh_from_db()
            self.assertEqual(card.example_vi, OLD_MATCH['example_vi'])
            self.assertTrue(card.content.is_published)
            self.assertIn('DRY RUN', output.getvalue())
            self.assertIn('NHÁP/CHƯA XUẤT BẢN', output.getvalue())
            self.assertIn('1 thẻ, 0 câu hỏi', output.getvalue())

    def test_apply_changes_only_exact_known_corruption_and_requires_new_review(self):
        card = self.make_old()
        before = {field.name: getattr(card, field.name) for field in Flashcard._meta.fields}
        call_command('repair_starter_trip', apply=True, stdout=StringIO())
        card.refresh_from_db()
        after = {field.name: getattr(card, field.name) for field in Flashcard._meta.fields}
        self.assertEqual({key for key in before if before[key] != after[key]}, set(REPAIRED_VALUES))
        self.assertEqual(card.example_vi, REPAIRED_VALUES['example_vi'])
        card.content.refresh_from_db()
        self.assertFalse(card.content.is_published)
        self.assertEqual(card.content.review_status, 'draft')
        updated_at = card.content.updated_at
        call_command('repair_starter_trip', apply=True, stdout=StringIO())
        card.content.refresh_from_db()
        self.assertEqual(card.content.updated_at, updated_at)

    def test_modified_translation_or_source_is_never_overwritten(self):
        for changes in ({'example_vi': 'Teacher translation'}, {'source_name': 'Teacher source'}, {'order': 610}):
            with self.subTest(changes=changes):
                card = self.make_old(**changes)
                call_command('repair_starter_trip', apply=True, stdout=StringIO())
                card.refresh_from_db()
                self.assertEqual(card.topic, OLD_MATCH['topic'])
                card.content.refresh_from_db()
                self.assertTrue(card.content.is_published)
                card.content.delete()

    def test_multiple_exact_matches_are_rejected_without_partial_changes(self):
        card = self.make_old()
        Flashcard.objects.create(content=card.content, **OLD_MATCH)
        with self.assertRaises(CommandError):
            call_command('repair_starter_trip', apply=True, stdout=StringIO())
        self.assertEqual(Flashcard.objects.filter(example_vi=OLD_MATCH['example_vi']).count(), 2)
