"""
Authentication regression tests — November 2026 pre-launch audit.

    FN-05 / S-04  Login never reveals an account's existence or state to a
                  caller who does not know the password.
    S-02          Login attempts are rate limited per IP and per account.
    S-05          Markup is refused in first / last names.
    S-07          The OpenAPI schema is not public outside DEBUG.
    S-09          The marketing campaign list is admin-only.
    LAN-34        A non-production environment only mails allow-listed people.
"""

from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from ooskillsbackend import mailer
from users.models import User, UserStatus
from users.throttles import LoginEmailThrottle

LOGIN_URL = '/api/auth/login/'
GENERIC = 'Email ou mot de passe incorrect.'


def _detail(resp):
    detail = resp.data.get('detail')
    return str(detail[0] if isinstance(detail, list) else detail)


class LoginEnumerationTests(APITestCase):
    def setUp(self):
        self.verified = User.objects.create_user(
            email='ok@test.com', password='Right-Pass-123', email_verified=True,
        )
        self.unverified = User.objects.create_user(
            email='pending@test.com', password='Right-Pass-123', email_verified=False,
        )
        self.suspended = User.objects.create_user(
            email='suspended@test.com', password='Right-Pass-123', email_verified=True,
            status=UserStatus.SUSPENDED,
        )

    def _login(self, email, password):
        return self.client.post(LOGIN_URL, {'email': email, 'password': password}, format='json')

    def test_wrong_password_gives_the_same_answer_whatever_the_account_state(self):
        for email in ('nobody@test.com', 'ok@test.com', 'pending@test.com', 'suspended@test.com'):
            with self.subTest(email=email):
                resp = self._login(email, 'wrong-password')
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(_detail(resp), GENERIC)
                self.assertNotIn('code', resp.data)

    def test_right_password_on_unverified_account_explains_the_state(self):
        resp = self._login('pending@test.com', 'Right-Pass-123')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('vérifié', _detail(resp))
        self.assertIn('code', resp.data)

    def test_right_password_on_verified_account_logs_in(self):
        resp = self._login('ok@test.com', 'Right-Pass-123')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertNotIn('refresh', resp.data)  # refresh travels in the HttpOnly cookie


class LoginThrottleTests(APITestCase):
    """The test settings neutralise throttling, so a real rate is patched in."""

    def setUp(self):
        cache.clear()
        User.objects.create_user(
            email='victim@test.com', password='Right-Pass-123', email_verified=True,
        )
        self.addCleanup(cache.clear)

    def _attempt(self, ip):
        return self.client.post(
            LOGIN_URL, {'email': 'Victim@test.com', 'password': 'guess'},
            format='json', REMOTE_ADDR=ip,
        )

    def test_account_is_protected_even_when_the_attacker_rotates_ip(self):
        original = LoginEmailThrottle.THROTTLE_RATES
        LoginEmailThrottle.THROTTLE_RATES = {**original, 'auth_login_email': '3/hour'}
        self.addCleanup(setattr, LoginEmailThrottle, 'THROTTLE_RATES', original)

        codes = [self._attempt(f'10.0.0.{i}').status_code for i in range(1, 6)]
        self.assertEqual(codes[:3], [400, 400, 400])
        self.assertEqual(codes[3:], [429, 429])


class NameValidationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='me@test.com', password='Right-Pass-123', email_verified=True,
            first_name='Amina',
        )
        self.client.force_authenticate(self.user)

    def test_markup_in_name_is_refused(self):
        resp = self.client.patch(
            '/api/auth/me/', {'first_name': '<script>alert(1)</script>'}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Amina')

    def test_real_names_are_accepted(self):
        for name in ('Jean-Pierre', "O'Brien", 'أمينة', 'Aït Ahmed'):
            with self.subTest(name=name):
                resp = self.client.patch('/api/auth/me/', {'first_name': name}, format='json')
                self.assertEqual(resp.status_code, status.HTTP_200_OK)
                self.assertEqual(resp.data['first_name'], name)


class ExposureTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='u@test.com', password='pw', role='USER')
        self.admin = User.objects.create_user(
            email='a@test.com', password='pw', role='ADMIN', is_staff=True,
        )

    def test_schema_and_docs_are_not_public(self):
        for url in ('/api/schema/', '/api/docs/', '/api/redoc/'):
            with self.subTest(url=url):
                self.assertIn(
                    self.client.get(url).status_code,
                    (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
                )
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get('/api/schema/').status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_read_schema(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get('/api/schema/').status_code, status.HTTP_200_OK)

    def test_campaign_list_is_admin_only_but_active_stays_public(self):
        url = '/api/formation/marketing-campaigns/'
        self.assertIn(
            self.client.get(url).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
        self.assertEqual(self.client.get(url + 'active/').status_code, status.HTTP_200_OK)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)


class MailerAllowlistTests(APITestCase):
    def setUp(self):
        self.sent = []
        original = mailer.resend.Emails.send
        mailer.resend.Emails.send = lambda params: self.sent.append(params) or {'id': 'x'}
        self.addCleanup(setattr, mailer.resend.Emails, 'send', original)

    @override_settings(EMAIL_RECIPIENT_ALLOWLIST=[])
    def test_no_allowlist_sends_to_everyone(self):
        mailer.send_email({'to': ['someone@gmail.com'], 'subject': 's'})
        self.assertEqual(len(self.sent), 1)

    @override_settings(EMAIL_RECIPIENT_ALLOWLIST=['@ooskills.com', 'qa@example.org'])
    def test_allowlist_drops_other_recipients(self):
        self.assertEqual(
            mailer.send_email({'to': ['someone@gmail.com'], 'subject': 's'}),
            {'id': 'suppressed'},
        )
        self.assertEqual(self.sent, [])
        mailer.send_email({'to': ['Dev@OOSkills.com', 'x@gmail.com', 'qa@example.org']})
        self.assertEqual(self.sent[0]['to'], ['Dev@OOSkills.com', 'qa@example.org'])
