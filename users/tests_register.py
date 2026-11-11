"""
Sign-up flow — November 2026 pre-launch audit.

    FN-06 / S-08 / UX-09  Registration opens no session: the user logs in only
                          after clicking the activation link.
    S-04                  Registration and "resend verification" answer the
                          same way whether the address is new or already used.
    FN-18                 /auth/register/ accepts JSON as well as multipart.
    LAN-19 / LAN-20       Terms acceptance (version + date) and the minimum-age
                          declaration are required and stored on the account.
    UX-21                 The language chosen at sign-up is stored.
"""

import uuid
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User

REGISTER = '/api/auth/register/'
RESEND = '/api/auth/resend-verification/'


class _SyncThread:
    """Run background e-mail threads inline so the tests can see the calls."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def _payload(**overrides):
    data = {
        'email': 'new.learner@test.com',
        'password': 'Strong-Pass-2026!',
        'password_confirm': 'Strong-Pass-2026!',
        'first_name': 'Amine',
        'last_name': 'Benali',
        'accept_terms': True,
        'age_confirmed': True,
        'language': 'ar',
    }
    data.update(overrides)
    return data


@override_settings(TERMS_VERSION='2026-11-09')
class RegisterTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        patches = [
            mock.patch('threading.Thread', _SyncThread),
            mock.patch('users.serializers.create_supabase_auth_user',
                       side_effect=lambda **kw: {'id': str(uuid.uuid4())}),
        ]
        self.verify_mail = mock.patch('users.views.send_verification_email').start()
        self.exists_mail = mock.patch('users.views.send_account_exists_email').start()
        for p in patches:
            p.start()
        self.addCleanup(mock.patch.stopall)

    def _register(self, fmt='json', **overrides):
        return self.client.post(REGISTER, _payload(**overrides), format=fmt)

    def test_new_account_gets_an_email_but_no_session(self):
        resp = self._register()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertNotIn('tokens', resp.data)
        self.assertNotIn('user', resp.data)
        self.assertNotIn('refresh_token', resp.cookies)
        user = User.objects.get(email='new.learner@test.com')
        self.verify_mail.assert_called_once_with(user)
        self.assertFalse(user.email_verified)

    def test_consent_language_and_age_are_stored(self):
        self._register()
        user = User.objects.get(email='new.learner@test.com')
        self.assertEqual(user.language, 'ar')
        self.assertEqual(user.terms_version, '2026-11-09')
        self.assertIsNotNone(user.terms_accepted_at)
        self.assertTrue(user.age_confirmed)

    def test_terms_and_age_are_required(self):
        for field in ('accept_terms', 'age_confirmed'):
            for value in (False, None):
                with self.subTest(field=field, value=value):
                    data = _payload()
                    if value is None:
                        data.pop(field)
                    else:
                        data[field] = value
                    resp = self.client.post(REGISTER, data, format='json')
                    self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertIn(field, resp.data)
        self.assertFalse(User.objects.exists())

    def test_multipart_still_works(self):
        resp = self._register(fmt='multipart', accept_terms='true', age_confirmed='true')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_existing_address_gets_the_same_answer_and_an_email(self):
        first = self._register()
        owner = User.objects.get(email='new.learner@test.com')
        owner.email_verified = True
        owner.save()
        self.verify_mail.reset_mock()

        again = self._register(email='New.Learner@test.com', password='Other-Pass-2026!',
                               password_confirm='Other-Pass-2026!')
        self.assertEqual(again.status_code, first.status_code)
        self.assertEqual(again.data['message'], first.data['message'])
        self.assertEqual(set(again.data), set(first.data))
        self.assertEqual(User.objects.count(), 1)
        self.exists_mail.assert_called_once_with(owner)
        self.verify_mail.assert_not_called()
        owner.refresh_from_db()
        self.assertTrue(owner.check_password('Strong-Pass-2026!'))

    def test_existing_unverified_address_gets_a_new_activation_link(self):
        self._register()
        self.verify_mail.reset_mock()
        self._register()
        self.verify_mail.assert_called_once()
        self.exists_mail.assert_not_called()


class ResendVerificationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.mail = mock.patch('users.views.send_verification_email').start()
        self.addCleanup(mock.patch.stopall)
        User.objects.create_user(email='pending@test.com', password='x-Pass-2026!', email_verified=False)
        User.objects.create_user(email='done@test.com', password='x-Pass-2026!', email_verified=True)

    def test_same_answer_for_unknown_pending_and_verified(self):
        answers = {
            email: self.client.post(RESEND, {'email': email}, format='json')
            for email in ('nobody@test.com', 'pending@test.com', 'done@test.com')
        }
        self.assertEqual({r.status_code for r in answers.values()}, {200})
        self.assertEqual(len({r.data['message'] for r in answers.values()}), 1)
        self.mail.assert_called_once()
        self.assertEqual(self.mail.call_args.args[0].email, 'pending@test.com')
