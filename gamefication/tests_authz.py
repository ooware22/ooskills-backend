"""
Authorization regression tests for the gamification API.

Pins finding F-03 from the September 2026 penetration test: the
admin-achievements endpoint must reject non-admin write (and read) access.
"""

from rest_framework.test import APITestCase
from rest_framework import status

from users.models import User
from gamefication.models import AchievementDefinition, ConditionType


class AdminAchievementAuthzTests(APITestCase):
    URL = '/api/gamification/admin-achievements/'

    def setUp(self):
        self.user = User.objects.create_user(
            email='student@test.com', password='pw', role='USER',
        )
        self.admin = User.objects.create_user(
            email='admin@test.com', password='pw', role='ADMIN', is_staff=True,
        )
        self.payload = {
            'key': 'hack_test',
            'condition_type': ConditionType.LESSONS_COMPLETED,
            'condition_value': 1,
        }

    # ── create ──────────────────────────────────────────────────────────────
    def test_anonymous_cannot_create(self):
        resp = self.client.post(self.URL, self.payload, format='json')
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertFalse(AchievementDefinition.objects.filter(key='hack_test').exists())

    def test_regular_user_cannot_create(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(self.URL, self.payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(AchievementDefinition.objects.filter(key='hack_test').exists())

    def test_admin_can_create(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(self.URL, self.payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(AchievementDefinition.objects.filter(key='hack_test').exists())

    # ── list ────────────────────────────────────────────────────────────────
    def test_regular_user_cannot_list(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_list(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.URL).status_code, status.HTTP_200_OK)

    # ── delete ──────────────────────────────────────────────────────────────
    def test_regular_user_cannot_delete(self):
        obj = AchievementDefinition.objects.create(
            key='legit', condition_type=ConditionType.LESSONS_COMPLETED, condition_value=1,
        )
        self.client.force_authenticate(self.user)
        resp = self.client.delete(f'{self.URL}{obj.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(AchievementDefinition.objects.filter(id=obj.id).exists())

    def test_admin_can_delete(self):
        obj = AchievementDefinition.objects.create(
            key='legit', condition_type=ConditionType.LESSONS_COMPLETED, condition_value=1,
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.delete(f'{self.URL}{obj.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(AchievementDefinition.objects.filter(id=obj.id).exists())
