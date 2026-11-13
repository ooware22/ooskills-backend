"""The staging end-to-end test account."""
import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from users.models import User

PW = 'a-long-test-password-123'


@override_settings(ENVIRONMENT='staging')
class EnsureE2EUserTests(TestCase):
    def run_cmd(self, *args, pw=PW):
        with mock.patch.dict(os.environ, {'E2E_USER_PASSWORD': pw}):
            call_command('ensure_e2e_user', *args, stdout=StringIO())

    def test_creates_a_verified_active_account(self):
        self.run_cmd()
        user = User.objects.get(email='e2e@ooskills.com')
        self.assertTrue(user.email_verified)
        self.assertEqual(user.status, 'ACTIVE')
        self.assertTrue(user.check_password(PW))

    def test_rerun_keeps_the_password_hash_when_unchanged(self):
        self.run_cmd()
        before = User.objects.get(email='e2e@ooskills.com').password
        self.run_cmd('--reset')
        self.assertEqual(User.objects.get(email='e2e@ooskills.com').password, before)

    def test_without_password_does_nothing(self):
        self.run_cmd(pw='')
        self.assertFalse(User.objects.filter(email='e2e@ooskills.com').exists())

    @override_settings(ENVIRONMENT='production')
    def test_refuses_in_production(self):
        with self.assertRaises(CommandError):
            self.run_cmd()
