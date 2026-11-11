"""
Keep one verified test account on staging for the automated end-to-end test
(the sign-up e-mail can't be opened by a script).

The password comes from the E2E_USER_PASSWORD environment variable (a GitHub
secret passed by the staging deploy). Without it, the command does nothing.
It refuses to run when ENVIRONMENT=production.

--reset removes the account's orders, enrolments and certificates so each
test run starts from a new learner.

    E2E_USER_PASSWORD=... python manage.py ensure_e2e_user --reset
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from users.models import User, UserStatus

DEFAULT_EMAIL = 'e2e@ooskills.com'


class Command(BaseCommand):
    help = 'Create or refresh the verified end-to-end test account (staging only).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help="Delete the account's orders, enrolments and certificates.")

    def handle(self, *args, **options):
        if getattr(settings, 'ENVIRONMENT', 'production') == 'production':
            raise CommandError('Refusing: the end-to-end test account is for staging only.')

        password = os.environ.get('E2E_USER_PASSWORD', '')
        email = os.environ.get('E2E_USER_EMAIL', DEFAULT_EMAIL).strip().lower()
        if not password:
            self.stdout.write('E2E_USER_PASSWORD is not set: no test account created.')
            return
        if len(password) < 12:
            raise CommandError('E2E_USER_PASSWORD must be at least 12 characters.')

        with transaction.atomic():
            user = User.objects.filter(email__iexact=email).first()
            created = user is None
            if created:
                user = User(email=email, first_name='Test', last_name='Automatique')
            user.email_verified = True
            user.status = UserStatus.ACTIVE
            user.is_active = True
            user.language = 'fr'
            if not user.terms_accepted_at:
                user.terms_accepted_at = timezone.now()
                user.terms_version = getattr(settings, 'TERMS_VERSION', '')
                user.age_confirmed = True
            # Only touch the password when it changed: setting it again would
            # log the account out everywhere for nothing.
            if created or not user.check_password(password):
                user.set_password(password)
            user.save()

            if options['reset'] and not created:
                orders = user.orders.all().delete()[0]
                enrolments = user.enrollments.all().delete()[0]
                certificates = user.certificates.all().delete()[0]
                self.stdout.write(f'Reset: {orders} order rows, {enrolments} enrolment rows, '
                                  f'{certificates} certificate rows deleted.')

        self.stdout.write(self.style.SUCCESS(
            f'Test account {"created" if created else "ready"}: {email}'))
