from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse


@override_settings(PASSWORD_RESET_ENABLED=False)
class PasswordRecoveryGateTests(TestCase):
    def test_disabled_recovery_is_explicit_and_never_sends_mail(self):
        get_user_model().objects.create_user(username='owner', email='owner@example.test', password='valid-password-123')
        client = Client(enforce_csrf_checks=True)
        page = client.get(reverse('password_reset'))
        self.assertEqual(page.status_code, 503)
        self.assertContains(page, 'Khôi phục mật khẩu chưa sẵn sàng', status_code=503)
        self.assertIn('no-store', page['Cache-Control'])
        self.assertEqual(client.post(reverse('password_reset'), {'email': 'owner@example.test'}).status_code, 403)
        client.get(reverse('login'))
        token = client.cookies['csrftoken'].value
        with patch('django.core.mail.message.EmailMessage.send', side_effect=AssertionError('mail must not be sent')):
            response = client.post(reverse('password_reset'), {'email': 'owner@example.test', 'csrfmiddlewaretoken': token})
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, 'chưa hỗ trợ gửi email khôi phục', status_code=503)
        self.assertNotIn('_auth_user_id', client.session)
