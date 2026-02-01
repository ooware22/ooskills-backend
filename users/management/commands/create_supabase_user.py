"""
Management commands for syncing users between Django and Supabase Auth.

Usage:
    # Create a user in both Django and Supabase Auth
    python manage.py create_supabase_user --email admin@example.com --password MyPass123! --role SUPER_ADMIN

    # Sync existing Django user to Supabase Auth
    python manage.py sync_to_supabase --email admin@example.com
"""

import os
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from users.models import User, UserRole, UserStatus

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


class Command(BaseCommand):
    help = 'Create a user in both Django and Supabase Auth'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, required=True, help='User email')
        parser.add_argument('--password', type=str, required=True, help='User password')
        parser.add_argument('--first-name', type=str, default='', help='First name')
        parser.add_argument('--last-name', type=str, default='', help='Last name')
        parser.add_argument(
            '--role', 
            type=str, 
            default='USER',
            choices=['USER', 'INSTRUCTOR', 'ADMIN', 'SUPER_ADMIN'],
            help='User role'
        )
        parser.add_argument(
            '--skip-supabase',
            action='store_true',
            help='Skip creating user in Supabase Auth (Django only)'
        )

    def handle(self, *args, **options):
        email = options['email']
        password = options['password']
        first_name = options['first_name']
        last_name = options['last_name']
        role = options['role']
        skip_supabase = options['skip_supabase']

        # Check if user already exists in Django
        if User.objects.filter(email=email).exists():
            raise CommandError(f'User with email {email} already exists in Django.')

        supabase_user_id = None

        # Create in Supabase Auth first (if not skipping)
        if not skip_supabase:
            if not SUPABASE_AVAILABLE:
                self.stdout.write(self.style.WARNING(
                    'supabase-py not installed. Install with: pip install supabase\n'
                    'Creating Django user only...'
                ))
            else:
                supabase_user_id = self.create_supabase_user(email, password, first_name, last_name)
                if supabase_user_id:
                    self.stdout.write(self.style.SUCCESS(
                        f'✓ Created user in Supabase Auth: {supabase_user_id}'
                    ))

        # Create in Django
        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            status=UserStatus.ACTIVE,
            email_verified=True,
            supabase_id=supabase_user_id,
        )

        # If ADMIN or SUPER_ADMIN, set is_staff
        if role in ['ADMIN', 'SUPER_ADMIN']:
            user.is_staff = True
            if role == 'SUPER_ADMIN':
                user.is_superuser = True
            user.save()

        self.stdout.write(self.style.SUCCESS(
            f'✓ Created user in Django: {user.id}'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ User created successfully!\n'
            f'   Email: {email}\n'
            f'   Role: {role}\n'
            f'   Django ID: {user.id}\n'
            f'   Supabase ID: {supabase_user_id or "N/A"}'
        ))

    def create_supabase_user(self, email: str, password: str, first_name: str, last_name: str):
        """Create user in Supabase Auth using Admin API."""
        supabase_url = getattr(settings, 'SUPABASE_URL', '') or os.environ.get('SUPABASE_URL', '')
        service_role_key = getattr(settings, 'SUPABASE_SERVICE_ROLE_KEY', '') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')

        if not supabase_url or not service_role_key:
            self.stdout.write(self.style.WARNING(
                'SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not configured.\n'
                'Set them in .env or settings.py\n'
                'Creating Django user only...'
            ))
            return None

        try:
            # Create Supabase client with service role key (admin access)
            supabase: Client = create_client(supabase_url, service_role_key)

            # Create user via Admin API
            response = supabase.auth.admin.create_user({
                'email': email,
                'password': password,
                'email_confirm': True,  # Auto-confirm email
                'user_metadata': {
                    'full_name': f'{first_name} {last_name}'.strip(),
                    'first_name': first_name,
                    'last_name': last_name,
                }
            })

            if response.user:
                return str(response.user.id)
            else:
                self.stdout.write(self.style.ERROR(
                    f'Failed to create Supabase user: No user returned'
                ))
                return None

        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'Failed to create Supabase user: {str(e)}'
            ))
            return None
