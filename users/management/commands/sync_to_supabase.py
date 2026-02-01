"""
Sync existing Django users to Supabase Auth.

Usage:
    # Sync a specific user
    python manage.py sync_to_supabase --email admin@example.com --password NewPass123!

    # Sync all users without supabase_id (requires password reset)
    python manage.py sync_to_supabase --all --default-password TempPass123!
"""

import os
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from users.models import User

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


class Command(BaseCommand):
    help = 'Sync existing Django users to Supabase Auth'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, help='Specific user email to sync')
        parser.add_argument('--password', type=str, help='Password for the Supabase user')
        parser.add_argument('--all', action='store_true', help='Sync all users without supabase_id')
        parser.add_argument('--default-password', type=str, help='Default password for --all sync')

    def handle(self, *args, **options):
        if not SUPABASE_AVAILABLE:
            raise CommandError('supabase-py not installed. Install with: pip install supabase')

        supabase_url = getattr(settings, 'SUPABASE_URL', '') or os.environ.get('SUPABASE_URL', '')
        service_role_key = getattr(settings, 'SUPABASE_SERVICE_ROLE_KEY', '') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')

        if not supabase_url or not service_role_key:
            raise CommandError(
                'SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured.\n'
                'Set them in .env or settings.py'
            )

        supabase: Client = create_client(supabase_url, service_role_key)

        if options['email']:
            self.sync_single_user(supabase, options['email'], options['password'])
        elif options['all']:
            if not options['default_password']:
                raise CommandError('--default-password is required when using --all')
            self.sync_all_users(supabase, options['default_password'])
        else:
            raise CommandError('Specify --email or --all')

    def sync_single_user(self, supabase: 'Client', email: str, password: str):
        """Sync a single user to Supabase Auth."""
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f'User with email {email} not found in Django.')

        if user.supabase_id:
            self.stdout.write(self.style.WARNING(
                f'User {email} already has supabase_id: {user.supabase_id}'
            ))
            return

        if not password:
            raise CommandError('--password is required to create Supabase Auth user')

        supabase_id = self.create_in_supabase(supabase, user, password)
        if supabase_id:
            user.supabase_id = supabase_id
            user.save(update_fields=['supabase_id'])
            self.stdout.write(self.style.SUCCESS(
                f'✓ Synced {email} to Supabase Auth: {supabase_id}'
            ))

    def sync_all_users(self, supabase: 'Client', default_password: str):
        """Sync all users without supabase_id to Supabase Auth."""
        users = User.objects.filter(supabase_id__isnull=True)
        total = users.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS('All users already have supabase_id'))
            return

        self.stdout.write(f'Syncing {total} users to Supabase Auth...\n')

        success = 0
        failed = 0

        for user in users:
            supabase_id = self.create_in_supabase(supabase, user, default_password)
            if supabase_id:
                user.supabase_id = supabase_id
                user.save(update_fields=['supabase_id'])
                self.stdout.write(self.style.SUCCESS(f'  ✓ {user.email}'))
                success += 1
            else:
                self.stdout.write(self.style.ERROR(f'  ✗ {user.email}'))
                failed += 1

        self.stdout.write(f'\nComplete: {success} synced, {failed} failed')

    def create_in_supabase(self, supabase: 'Client', user: User, password: str) -> str:
        """Create user in Supabase Auth."""
        try:
            response = supabase.auth.admin.create_user({
                'email': user.email,
                'password': password,
                'email_confirm': True,
                'user_metadata': {
                    'full_name': user.full_name,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'django_id': str(user.id),
                }
            })

            if response.user:
                return str(response.user.id)
            return None

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'    Error: {str(e)}'))
            return None
