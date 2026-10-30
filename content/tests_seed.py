"""Tests for the seed_landing_content management command."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from content.models import FAQItem, FeatureItem, HeroSection, Testimonial
from users.models import User


def seed():
    out = StringIO()
    call_command('seed_landing_content', stdout=out)
    return out.getvalue()


@override_settings(ENVIRONMENT='staging')
class SeedLandingContentTests(TestCase):

    def test_creates_content_and_active_endpoints_return_200(self):
        admin = User.objects.create_user(
            email='admin@test.com', password='pw', role='ADMIN', is_staff=True,
        )
        client = APIClient()
        client.force_authenticate(admin)

        # Before seeding: the exact 404s seen on an empty staging database.
        self.assertEqual(client.get('/api/admin/cms/hero/active/').status_code, 404)

        seed()

        for section in ('hero', 'features', 'faq'):
            resp = client.get(f'/api/admin/cms/{section}/active/')
            self.assertEqual(resp.status_code, 200, section)
        self.assertEqual(HeroSection.objects.filter(is_active=True).count(), 1)
        self.assertEqual(FeatureItem.objects.count(), 4)
        self.assertEqual(FAQItem.objects.count(), 3)
        self.assertEqual(Testimonial.objects.count(), 3)

    def test_public_landing_endpoint_has_data(self):
        seed()
        resp = APIClient().get('/api/public/landing/?lang=fr')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.data['hero'])
        self.assertIsNotNone(resp.data['features'])
        self.assertIsNotNone(resp.data['faq'])

    def test_rerun_is_idempotent_and_keeps_admin_edits(self):
        seed()
        hero = HeroSection.objects.get()
        hero.title = {'fr': 'Titre modifié', 'en': 'Edited', 'ar': 'معدل'}
        hero.save()

        output = seed()

        self.assertIn('Nothing to do', output)
        self.assertEqual(HeroSection.objects.count(), 1)
        self.assertEqual(FeatureItem.objects.count(), 4)
        hero.refresh_from_db()
        self.assertEqual(hero.title['en'], 'Edited')


class SeedProductionGuardTests(TestCase):

    @override_settings(ENVIRONMENT='production')
    def test_refuses_to_run_in_production(self):
        with self.assertRaises(CommandError):
            seed()
        self.assertEqual(HeroSection.objects.count(), 0)

    @override_settings(ENVIRONMENT='production')
    def test_force_overrides_the_guard(self):
        call_command('seed_landing_content', '--force', stdout=StringIO())
        self.assertEqual(HeroSection.objects.count(), 1)
