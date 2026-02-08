"""
User URL Configuration for OOSkills Platform

Authentication endpoints:
    /api/auth/register/          - User registration
    /api/auth/login/             - JWT login
    /api/auth/token/refresh/     - Refresh JWT token
    /api/auth/me/                - User profile
    /api/auth/change-password/   - Change password
    /api/auth/logout/            - Logout (blacklist token)
    /api/auth/my-referral-code/  - Get/generate referral code
    /api/auth/my-referrals/      - List referred users

Admin endpoints:
    /api/admin/users/            - User CRUD

Utility endpoints:
    /api/wilayas/                - List Algerian wilayas
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenRefreshView,
    TokenVerifyView,
)

from .views import (
    RegisterView,
    LoginView,
    ProfileView,
    ChangePasswordView,
    LogoutView,
    UploadAvatarView,
    VerifyEmailView,
    ResendVerificationView,
    MyReferralCodeView,
    MyReferralsView,
    AdminUserViewSet,
    WilayaListView,
    UserRolesView,
    UserStatusesView,
)


# =============================================================================
# ADMIN ROUTER
# =============================================================================

admin_router = DefaultRouter()
admin_router.register(r'users', AdminUserViewSet, basename='admin-users')


# =============================================================================
# URL PATTERNS
# =============================================================================

# Authentication URL patterns (prefix: /api/auth/)
auth_urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token-verify'),
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('resend-verification/', ResendVerificationView.as_view(), name='resend-verification'),
    path('me/', ProfileView.as_view(), name='profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('upload-avatar/', UploadAvatarView.as_view(), name='upload-avatar'),
    path('my-referral-code/', MyReferralCodeView.as_view(), name='my-referral-code'),
    path('my-referrals/', MyReferralsView.as_view(), name='my-referrals'),
]

# Utility URL patterns
utility_urlpatterns = [
    path('wilayas/', WilayaListView.as_view(), name='wilayas'),
    path('user-roles/', UserRolesView.as_view(), name='user-roles'),
    path('user-statuses/', UserStatusesView.as_view(), name='user-statuses'),
]

# Admin URL patterns (prefix: /api/admin/)
admin_urlpatterns = [
    path('', include(admin_router.urls)),
]

# Combined app URLs
app_name = 'users'

urlpatterns = [
    path('auth/', include((auth_urlpatterns, 'auth'))),
    path('admin/', include((admin_urlpatterns, 'admin'))),
    path('', include(utility_urlpatterns)),
]
