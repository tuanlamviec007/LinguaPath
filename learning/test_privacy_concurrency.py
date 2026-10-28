"""PostgreSQL checks for a link racing a private export."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from .privacy import _has_social_data


@skipUnlessDBFeature('has_select_for_no_key_update')
class PrivacyAttachmentConcurrencyTests(TransactionTestCase):
    def test_new_social_fk_cannot_commit_during_export(self):
        with connection.cursor() as cursor:
            if 'socialaccount_socialaccount' in connection.introspection.table_names(cursor):
                self.skipTest('Fixture requires allauth disabled in this disposable CI database')
            user_table = connection.ops.quote_name(get_user_model()._meta.db_table)
            cursor.execute('CREATE TABLE socialaccount_socialaccount (id integer PRIMARY KEY, '
                           f'user_id integer NOT NULL REFERENCES {user_table}(id) DEFERRABLE INITIALLY DEFERRED)')
        self._created_fixture = True
        self.addCleanup(self._remove_fixture_table)
        user = get_user_model().objects.create_user(username='privacy-race', password='privacy-password-123')
        paused, release, inserted, linked = Event(), Event(), Event(), Event()

        def pause_after_check(target):
            result = _has_social_data(target)
            paused.set()
            if not release.wait(10):
                raise AssertionError('Export was not released')
            return result

        def export():
            close_old_connections()
            try:
                client = Client()
                client.force_login(get_user_model().objects.get(pk=user.pk))
                with patch('learning.privacy._has_social_data', side_effect=pause_after_check):
                    return client.post(reverse('privacy_center'), {'action': 'export', 'password': 'privacy-password-123'}).status_code
            finally:
                release.set()
                connections.close_all()

        def link():
            close_old_connections()
            try:
                if not paused.wait(10):
                    raise AssertionError('Export did not reach its guard')
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '8s'")
                        cursor.execute('INSERT INTO socialaccount_socialaccount (id, user_id) VALUES (%s, %s)', [1, user.pk])
                        inserted.set()
                        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                    linked.set()
            finally:
                inserted.set()
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(export)
            b = executor.submit(link)
            try:
                self.assertTrue(inserted.wait(10), 'The concurrent link did not start')
                self.assertFalse(linked.wait(.5), 'The FK check should wait for the export lock')
            finally:
                release.set()
            self.assertEqual(a.result(timeout=15), 200)
            b.result(timeout=15)
        self.assertTrue(linked.is_set())
        client = Client()
        client.force_login(user)
        response = client.post(reverse('privacy_center'), {'action': 'export', 'password': 'privacy-password-123'})
        self.assertEqual(response.status_code, 409)

    def tearDown(self):
        self._remove_fixture_table()
        super().tearDown()

    def _remove_fixture_table(self):
        if getattr(self, '_created_fixture', False):
            with connection.cursor() as cursor:
                cursor.execute('DROP TABLE IF EXISTS socialaccount_socialaccount')
            self._created_fixture = False
