"""
Change password from the account settings — November 2026 pre-launch audit.

    FN-08  A logged-in user can change their password (screen in settings).
    FN-09  Changing (or resetting) the password ends every other session:
           access and refresh tokens issued before the change stop working.
"""

from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User

URL = '/api/auth/change-password/'
ME = '/api/auth/me/'
REFRESH = '/api/auth/token/refresh/'
OLD = 'Old-Pass-2026!'
NEW = 'Brand-New-Pass-2026!'


class ChangePasswordTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(email='learner@test.com', password=OLD, email_verified=True)
        self.refresh = RefreshToken.for_user(self.user)
        self.access = str(self.refresh.access_token)

    def _auth(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

    def _change(self, method='post', **overrides):
        body = {'old_password': OLD, 'new_password': NEW, 'new_password_confirm': NEW, **overrides}
        self._auth(self.access)
        return getattr(self.client, method)(URL, body, format='json')

    def test_post_and_put_both_change_the_password(self):
        for method in ('post', 'put'):
            with self.subTest(method=method):
                self.user.set_password(OLD)
                self.user.save()
                self.refresh = RefreshToken.for_user(self.user)
                self.access = str(self.refresh.access_token)
                resp = self._change(method)
                self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
                self.user.refresh_from_db()
                self.assertTrue(self.user.check_password(NEW))

    def test_wrong_current_password_is_refused(self):
        resp = self._change(old_password='not-my-password')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('old_password', resp.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))

    def test_confirmation_must_match(self):
        resp = self._change(new_password_confirm='Something-Else-2026!')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password_confirm', resp.data)

    def test_weak_new_password_is_refused(self):
        resp = self._change(new_password='123', new_password_confirm='123')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', resp.data)

    def test_requires_login(self):
        resp = self.client.post(URL, {'old_password': OLD, 'new_password': NEW,
                                      'new_password_confirm': NEW}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_old_tokens_stop_working_and_the_new_one_works(self):
        resp = self._change()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        new_access = resp.data['tokens']['access']
        self.assertIn('refresh_token', resp.cookies)

        # Another browser holding the old access token is logged out.
        self._auth(self.access)
        self.assertEqual(self.client.get(ME).status_code, status.HTTP_401_UNAUTHORIZED)

        # ...and cannot get a new access token with its old refresh cookie.
        self.client.credentials()
        self.client.cookies['refresh_token'] = str(self.refresh)
        refreshed = self.client.post(REFRESH)
        self.assertEqual(refreshed.status_code, status.HTTP_401_UNAUTHORIZED)

        # The browser that made the change stays logged in.
        self._auth(new_access)
        self.assertEqual(self.client.get(ME).status_code, status.HTTP_200_OK)

    def test_new_refresh_cookie_still_refreshes(self):
        resp = self._change()
        self.client.credentials()
        self.client.cookies['refresh_token'] = resp.cookies['refresh_token'].value
        refreshed = self.client.post(REFRESH)
        self.assertEqual(refreshed.status_code, status.HTTP_200_OK)
        self._auth(refreshed.data['access'])
        self.assertEqual(self.client.get(ME).status_code, status.HTTP_200_OK)

    def test_attempts_are_rate_limited(self):
        # The test settings neutralise throttling, so the real rate is patched in.
        from django.conf import settings
        from rest_framework.throttling import ScopedRateThrottle
        original = ScopedRateThrottle.THROTTLE_RATES
        real = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
        ScopedRateThrottle.THROTTLE_RATES = {**original, 'auth_password_change': '5/min'}
        self.addCleanup(setattr, ScopedRateThrottle, 'THROTTLE_RATES', original)
        self.assertIn('auth_password_change', real)

        codes = [self._change(old_password=f'guess-{i}').status_code for i in range(7)]
        self.assertEqual(codes[:5], [400] * 5)
        self.assertEqual(codes[5:], [429, 429])

    def test_profile_says_whether_the_account_has_a_password(self):
        self._auth(self.access)
        self.assertIs(self.client.get(ME).data['has_password'], True)

        social = User.objects.create_user(email='google@test.com', email_verified=True)
        self._auth(str(RefreshToken.for_user(social).access_token))
        self.assertIs(self.client.get(ME).data['has_password'], False)
