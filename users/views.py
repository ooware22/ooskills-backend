"""
User Views for OOSkills Platform

Provides endpoints for:
- Authentication (register, login, password reset)
- User profile management
- Admin user management
- Referral system
"""

from django.conf import settings as django_settings
from django.db import models
from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from django.contrib.auth import update_session_auth_hash

import logging
logger = logging.getLogger(__name__)


# =============================================================================
# REFRESH-TOKEN COOKIE HELPERS
# =============================================================================

_REFRESH_COOKIE_NAME = 'refresh_token'
_REFRESH_COOKIE_PATH = '/api/auth/'
_REFRESH_MAX_AGE = 7 * 24 * 3600  # 7 days


def _refresh_cookie_security_options():
    """Return (secure, samesite) for refresh-token cookies.

    In production, FRONTEND_URL is HTTPS and cross-origin, so cookies must be
    Secure + SameSite=None. In local dev (http://localhost), use Lax + non-secure.
    This remains correct even if DEBUG is accidentally left True in production.
    """
    frontend_url = str(getattr(django_settings, 'FRONTEND_URL', '') or '')
    frontend_is_https = frontend_url.startswith('https://')
    secure = frontend_is_https or (not django_settings.DEBUG)
    samesite = 'None' if secure else 'Lax'
    return secure, samesite


def _set_refresh_cookie(response, token_str: str):
    """Attach the refresh token as an HttpOnly cookie to *response*.

    JS can never read or modify this cookie — not even from XSS.
    - Production: Secure=True, SameSite=None  (required for cross-origin Vercel→Render)
    - Dev:        Secure=False, SameSite=Lax  (SameSite=None requires Secure=True)
    """
    secure, samesite = _refresh_cookie_security_options()

    response.set_cookie(
        _REFRESH_COOKIE_NAME,
        token_str,
        max_age=_REFRESH_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path=_REFRESH_COOKIE_PATH,
    )
    return response


def _clear_refresh_cookie(response):
    """Expire the refresh-token cookie immediately."""
    _, samesite = _refresh_cookie_security_options()

    response.delete_cookie(
        _REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
        samesite=samesite,
    )
    return response

from .storage import upload_avatar, delete_avatar
from .avatar_serializer import AvatarUploadSerializer
from .email import send_verification_email, verify_email_token, send_password_reset_email, verify_password_reset_token

from .models import User, UserRole, UserStatus, AuthProvider, ReferralCode, Referral, ALGERIAN_WILAYAS, AccountDeletionRequest, DeletionRequestStatus, Notification
from .serializers import (
    UserRegistrationSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    AdminUserSerializer,
    AdminUserCreateSerializer,
    AdminUserUpdateSerializer,
    ReferralCodeSerializer,
    ReferralSerializer,
    UserCompactSerializer,
    WilayaSerializer,
    CustomTokenObtainPairSerializer,
    AccountDeletionRequestSerializer,
    AdminDeletionRequestSerializer,
    AdminDeletionRequestUpdateSerializer,
    ConfirmAccountDeletionSerializer,
    NotificationSerializer,
)
from content.permissions import IsAdminOrSuperAdmin


# =============================================================================
# AUTHENTICATION VIEWS
# =============================================================================

class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/
    
    Register a new user account and send verification email.
    Supports multipart/form-data for avatar upload.
    """
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = UserRegistrationSerializer
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_register'
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Send verification email in background (non-blocking)
        import threading
        threading.Thread(target=send_verification_email, args=(user,), daemon=True).start()
        
        # Generate JWT tokens for the new user
        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)

        # Refresh token goes into an HttpOnly cookie — JS cannot read/modify it.
        response = Response({
            'user': UserProfileSerializer(user).data,
            'tokens': {
                'access': access,
                # 'refresh' intentionally omitted from body
            },
            'message': 'Inscription réussie. Veuillez vérifier votre email.'
        }, status=status.HTTP_201_CREATED)
        return _set_refresh_cookie(response, str(refresh))


class VerifyEmailView(APIView):
    """
    POST /api/auth/verify-email/
    
    Verify user email with token.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Skip all auth for this public endpoint
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_email'

    def post(self, request):
        token = request.data.get('token')

        if not token:
            return Response({
                'error': 'Token requis.'
            }, status=status.HTTP_400_BAD_REQUEST)

        success, user, message = verify_email_token(token)

        if success:
            return Response({
                'message': message,
                'user': UserProfileSerializer(user).data if user else None
            })
        else:
            return Response({
                'error': message
            }, status=status.HTTP_400_BAD_REQUEST)


class ResendVerificationView(APIView):
    """
    POST /api/auth/resend-verification/
    
    Resend verification email.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_email'
    
    def post(self, request):
        email = request.data.get('email')
        
        if not email:
            return Response({
                'error': 'Email requis.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't reveal if email exists
            return Response({
                'message': 'Si cet email existe, un lien de vérification a été envoyé.'
            })
        
        if user.email_verified:
            return Response({
                'message': 'Cet email est déjà vérifié.'
            })
        
        send_verification_email(user)
        
        return Response({
            'message': 'Si cet email existe, un lien de vérification a été envoyé.'
        })


class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/
    
    Login with email and password.
    Returns JWT tokens and user info.
    """
    permission_classes = [AllowAny]
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_login'

    def post(self, request, *args, **kwargs):
        """Set refresh token in HttpOnly cookie on successful login."""
        response = super().post(request, *args, **kwargs)
        if response.status_code != status.HTTP_200_OK:
            return response

        refresh_token = None
        if hasattr(response, 'data') and isinstance(response.data, dict):
            refresh_token = response.data.pop('refresh', None)

        if refresh_token:
            return _set_refresh_cookie(response, str(refresh_token))
        return response


class ProfileView(generics.RetrieveUpdateAPIView):
    """
    GET /api/auth/me/
    PATCH /api/auth/me/
    
    Get or update current user's profile.
    Supports multipart/form-data for avatar upload.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return UserProfileUpdateSerializer
        return UserProfileSerializer
    
    def get_object(self):
        return self.request.user
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', True)  # Always allow partial updates
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        # Refresh from DB to get fresh computed properties (e.g. avatar_display_url)
        instance.refresh_from_db()
        
        # Return full profile after update
        return Response(UserProfileSerializer(instance).data)


class ChangePasswordView(generics.UpdateAPIView):
    """
    POST /api/auth/change-password/
    
    Change user's password.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer
    
    def get_object(self):
        return self.request.user
    
    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = self.get_object()
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        # Update session to prevent logout
        update_session_auth_hash(request, user)
        
        return Response({
            'message': 'Mot de passe modifié avec succès.'
        })


class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/
    
    Request password reset email.
    Always returns success to avoid revealing if email exists.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset'
    
    def post(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        
        try:
            user = User.objects.get(email=email)
            
            # Only send if user account is not deleted
            if user.status != UserStatus.DELETED:
                logger.info(f"[FORGOT-PASSWORD] Sending reset email to {email}")
                result = send_password_reset_email(user)
                logger.info(f"[FORGOT-PASSWORD] Email send result for {email}: {result}")
        except User.DoesNotExist:
            pass  # Don't reveal if email exists
        except Exception as e:
            logger.error(f"[FORGOT-PASSWORD] Unexpected error for {email}: {type(e).__name__}: {e}", exc_info=True)
        
        # Always return success message
        return Response({
            'message': 'Si cet email existe, un lien de réinitialisation a été envoyé.'
        })


class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/
    
    Reset password using token from email.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset'
    
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']
        
        success, user, message = verify_password_reset_token(token)
        
        if not success:
            return Response({
                'error': message
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Mark token as used
        from .models import PasswordResetToken
        reset_token = PasswordResetToken.objects.get(token=token)
        reset_token.use_token()
        
        # Set new password
        user.set_password(new_password)
        user.save(update_fields=['password', 'updated_at'])
        
        return Response({
            'message': 'Mot de passe réinitialisé avec succès. Vous pouvez maintenant vous connecter.'
        })


class LogoutView(APIView):
    """
    POST /api/auth/logout/

    Blacklists the refresh token (from HttpOnly cookie) and clears the cookie.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh_str = request.COOKIES.get(_REFRESH_COOKIE_NAME)
        if refresh_str:
            try:
                refresh_token = RefreshToken(refresh_str)
                blacklist_fn = getattr(refresh_token, 'blacklist', None)
                if callable(blacklist_fn):
                    try:
                        blacklist_fn()
                    except Exception as e:
                        logger.warning(f'Refresh token blacklist skipped: {e}')
            except (TokenError, InvalidToken):
                pass  # Already expired/invalid — still clear the cookie
        response = Response({'message': 'Déconnexion réussie.'})
        return _clear_refresh_cookie(response)


class CookieTokenRefreshView(APIView):
    """
    POST /api/auth/token/refresh/

    Reads the refresh token from the HttpOnly cookie (never from the request body).
    Returns a new access token in the JSON body and rotates the refresh cookie.
    JS cannot intercept or modify the cookie — making token theft via XSS impossible.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_refresh'

    def post(self, request, *args, **kwargs):
        refresh_str = request.COOKIES.get(_REFRESH_COOKIE_NAME)
        if not refresh_str:
            return Response(
                {'detail': 'Refresh token manquant. Veuillez vous reconnecter.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            token = RefreshToken(refresh_str)
            access = str(token.access_token)
            # Rotate: generate a new refresh token and blacklist the old one
            new_refresh = str(token)
        except (TokenError, InvalidToken) as e:
            response = Response({'detail': str(e)}, status=status.HTTP_401_UNAUTHORIZED)
            return _clear_refresh_cookie(response)

        response = Response({'access': access})
        return _set_refresh_cookie(response, new_refresh)


class UploadAvatarView(APIView):
    """
    POST /api/auth/upload-avatar/

    Upload user profile photo to Supabase Storage.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        serializer = AvatarUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        avatar_file = serializer.validated_data['avatar']
        user = request.user
        
        try:
            # Delete old avatar if exists
            if user.avatar_url:
                delete_avatar(user.avatar_url)
            
            # Upload new avatar
            public_url = upload_avatar(avatar_file, str(user.id))
            
            # Update user's avatar_url
            user.avatar_url = public_url
            user.save(update_fields=['avatar_url', 'updated_at'])
            
            return Response({
                'message': 'Photo de profil mise à jour avec succès.',
                'avatar_url': public_url
            })
        except Exception as e:
            return Response({
                'error': 'Échec du téléchargement de la photo.',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SocialLoginView(APIView):
    """
    POST /api/auth/social-login/
    
    Authenticate with Google or Facebook OAuth.
    Accepts authorization code from frontend, exchanges it for user data,
    and returns JWT tokens.
    
    Request body:
        {
            "provider": "google" | "facebook",
            "code": "<authorization_code>",
            "redirect_uri": "<redirect_uri_used_in_frontend>"
        }
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_social'
    
    def post(self, request):
        provider = request.data.get('provider', '').lower()
        code = request.data.get('code')
        redirect_uri = request.data.get('redirect_uri')
        
        if not code:
            return Response(
                {'error': 'Authorization code is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not redirect_uri:
            return Response(
                {'error': 'Redirect URI is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if provider not in ('google', 'facebook'):
            return Response(
                {'error': 'Invalid provider. Must be "google" or "facebook".'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            if provider == 'google':
                user_data = self._google_authenticate(code, redirect_uri)
            else:
                user_data = self._facebook_authenticate(code, redirect_uri)
        except Exception as e:
            return Response(
                {'error': f'Authentication failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get or create the user
        user = self._get_or_create_user(user_data, provider)
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        access = str(refresh.access_token)
        response = Response({
            'user': UserProfileSerializer(user).data,
            'tokens': {
                'access': access,
                # 'refresh' intentionally omitted — sent as HttpOnly cookie
            },
            'message': 'Social login successful.'
        })
        return _set_refresh_cookie(response, str(refresh))
    
    def _google_authenticate(self, code, redirect_uri):
        """
        Exchange Google authorization code for user data.
        """
        import requests as http_requests
        from django.conf import settings as django_settings
        
        # Exchange code for access token
        token_response = http_requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'code': code,
                'client_id': django_settings.GOOGLE_CLIENT_ID,
                'client_secret': django_settings.GOOGLE_CLIENT_SECRET,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            },
            timeout=10,
        )
        
        if token_response.status_code != 200:
            raise ValueError(f'Google token exchange failed: {token_response.text}')
        
        token_data = token_response.json()
        access_token = token_data.get('access_token')
        
        if not access_token:
            raise ValueError('No access token received from Google.')
        
        # Fetch user profile
        profile_response = http_requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
        
        if profile_response.status_code != 200:
            raise ValueError('Failed to fetch Google user profile.')
        
        profile = profile_response.json()
        
        return {
            'email': profile.get('email'),
            'first_name': profile.get('given_name', ''),
            'last_name': profile.get('family_name', ''),
            'avatar_url': profile.get('picture'),
        }
    
    def _facebook_authenticate(self, code, redirect_uri):
        """
        Exchange Facebook authorization code for user data.
        """
        import requests as http_requests
        from django.conf import settings as django_settings
        
        # Exchange code for access token
        token_response = http_requests.get(
            'https://graph.facebook.com/v18.0/oauth/access_token',
            params={
                'client_id': django_settings.FACEBOOK_APP_ID,
                'client_secret': django_settings.FACEBOOK_APP_SECRET,
                'redirect_uri': redirect_uri,
                'code': code,
            },
            timeout=10,
        )
        
        if token_response.status_code != 200:
            raise ValueError(f'Facebook token exchange failed: {token_response.text}')
        
        token_data = token_response.json()
        access_token = token_data.get('access_token')
        
        if not access_token:
            raise ValueError('No access token received from Facebook.')
        
        # Fetch user profile
        profile_response = http_requests.get(
            'https://graph.facebook.com/me',
            params={
                'access_token': access_token,
                'fields': 'id,email,first_name,last_name,picture.type(large)',
            },
            timeout=10,
        )
        
        if profile_response.status_code != 200:
            raise ValueError('Failed to fetch Facebook user profile.')
        
        profile = profile_response.json()
        
        # Extract picture URL
        picture_data = profile.get('picture', {}).get('data', {})
        avatar_url = picture_data.get('url') if not picture_data.get('is_silhouette') else None
        
        return {
            'email': profile.get('email'),
            'first_name': profile.get('first_name', ''),
            'last_name': profile.get('last_name', ''),
            'avatar_url': avatar_url,
        }
    
    def _get_or_create_user(self, user_data, provider):
        """
        Get existing user by email or create new one.
        Social login users are auto-verified and active.
        Also creates a corresponding Supabase Auth user for new users.
        """
        from .storage import create_supabase_auth_user
        import logging
        logger = logging.getLogger(__name__)
        
        email = user_data.get('email')
        
        if not email:
            raise ValueError('Email not provided by the OAuth provider. Please ensure your account has an email.')
        
        auth_provider = AuthProvider.GOOGLE if provider == 'google' else AuthProvider.FACEBOOK
        
        try:
            # User already exists — just log them in
            user = User.objects.get(email=email)
            logger.info(f"Social login: existing user found for {email}, supabase_id={user.supabase_id}")
            
            # Create Supabase Auth user if missing
            if not user.supabase_id:
                logger.info(f"Social login: creating Supabase Auth user for existing user {email}")
                supabase_user = create_supabase_auth_user(
                    email=email,
                    user_metadata={
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'auth_provider': provider,
                    }
                )
                user.supabase_id = supabase_user['id']
                user.save(update_fields=['supabase_id', 'updated_at'])
                logger.info(f"Social login: Supabase Auth user created for {email}, id={supabase_user['id']}")
            
            # Update avatar if not set
            if not user.avatar_url and user_data.get('avatar_url'):
                user.avatar_url = user_data['avatar_url']
                user.save(update_fields=['avatar_url', 'updated_at'])
            
            return user
            
        except User.DoesNotExist:
            logger.info(f"Social login: creating new user for {email}")
            
            # Create user in Supabase Auth first
            supabase_user = create_supabase_auth_user(
                email=email,
                user_metadata={
                    'first_name': user_data.get('first_name', ''),
                    'last_name': user_data.get('last_name', ''),
                    'auth_provider': provider,
                }
            )
            supabase_id = supabase_user['id']
            logger.info(f"Social login: Supabase Auth user created for {email}, id={supabase_id}")
            
            # Create Django user
            user = User.objects.create_user(
                email=email,
                first_name=user_data.get('first_name', ''),
                last_name=user_data.get('last_name', ''),
                avatar_url=user_data.get('avatar_url'),
                email_verified=True,
                status=UserStatus.ACTIVE,
                auth_provider=auth_provider,
                supabase_id=supabase_id,
            )
            logger.info(f"Social login: Django user created for {email}, id={user.id}")
            return user

# =============================================================================
# REFERRAL VIEWS
# =============================================================================

class VerifyReferralCodeView(APIView):
    """
    POST /api/auth/verify-referral-code/
    
    Public endpoint to verify if a referral code is valid.
    Returns referrer info for UI feedback.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def post(self, request):
        code = request.data.get('code', '').strip()
        
        if not code:
            return Response(
                {'valid': False, 'message': 'Code requis.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            ref_code = ReferralCode.objects.select_related('user').get(
                code=code, is_active=True
            )
            return Response({
                'valid': True,
                'referrer_name': ref_code.user.first_name or ref_code.user.display_name,
            })
        except ReferralCode.DoesNotExist:
            return Response({
                'valid': False,
                'message': 'Code de parrainage invalide.'
            })

class MyReferralCodeView(APIView):
    """
    GET /api/auth/my-referral-code/
    POST /api/auth/my-referral-code/ (generate if not exists)
    
    Get or generate user's referral code.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            ref_code = request.user.referral_code
            return Response(ReferralCodeSerializer(ref_code).data)
        except ReferralCode.DoesNotExist:
            return Response({
                'message': 'Vous n\'avez pas encore de code de parrainage.',
                'code': None
            })
    
    def post(self, request):
        try:
            ref_code = request.user.referral_code
            return Response(ReferralCodeSerializer(ref_code).data)
        except ReferralCode.DoesNotExist:
            ref_code = ReferralCode.generate_code(request.user)
            return Response(
                ReferralCodeSerializer(ref_code).data,
                status=status.HTTP_201_CREATED
            )


class MyReferralsView(generics.ListAPIView):
    """
    GET /api/auth/my-referrals/
    
    List users referred by current user.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ReferralSerializer
    
    def get_queryset(self):
        return Referral.objects.filter(referrer=self.request.user).select_related(
            'referred', 'referral_code'
        ).order_by('-created_at')


# =============================================================================
# ADMIN USER MANAGEMENT VIEWS
# =============================================================================

class AdminUserViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for Users.
    
    GET /api/admin/users/ - List all users
    POST /api/admin/users/ - Create user (supports avatar upload)
    GET /api/admin/users/{id}/ - Get user
    PUT/PATCH /api/admin/users/{id}/ - Update user (supports avatar upload)
    DELETE /api/admin/users/{id}/ - Soft delete user
    """
    queryset = User.objects.all().order_by('-date_joined')
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return AdminUserCreateSerializer
        if self.action in ['update', 'partial_update']:
            return AdminUserUpdateSerializer
        return AdminUserSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by role
        role = self.request.query_params.get('role')
        if role:
            queryset = queryset.filter(role=role)
        
        # Filter by status
        user_status = self.request.query_params.get('status')
        if user_status:
            queryset = queryset.filter(status=user_status)
        
        # Filter by wilaya
        wilaya = self.request.query_params.get('wilaya')
        if wilaya:
            queryset = queryset.filter(wilaya=wilaya)
        
        # Search by email or name
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(email__icontains=search) |
                models.Q(first_name__icontains=search) |
                models.Q(last_name__icontains=search)
            )
        
        return queryset
    
    def destroy(self, request, *args, **kwargs):
        """Soft delete instead of hard delete."""
        user = self.get_object()
        user.soft_delete()
        return Response({'message': 'Utilisateur supprimé.'}, status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate user account."""
        user = self.get_object()
        user.activate()
        return Response(AdminUserSerializer(user).data)
    
    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        """Suspend user account."""
        user = self.get_object()
        user.suspend()
        return Response(AdminUserSerializer(user).data)
    
    @action(detail=True, methods=['post'])
    def promote_admin(self, request, pk=None):
        """Promote user to admin."""
        user = self.get_object()
        user.promote_to_admin()
        return Response(AdminUserSerializer(user).data)
    
    @action(detail=True, methods=['post'])
    def promote_instructor(self, request, pk=None):
        """Promote user to instructor."""
        user = self.get_object()
        user.promote_to_instructor()
        return Response(AdminUserSerializer(user).data)


# =============================================================================
# UTILITY VIEWS
# =============================================================================

class WilayaListView(APIView):
    """
    GET /api/wilayas/
    
    Get list of Algerian wilayas (cached — static data).
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        from django.core.cache import cache
        from formation.cache import wilaya_list_key, WILAYA_TTL

        key = wilaya_list_key()
        cached = cache.get(key)
        if cached is not None:
            return Response(cached)
        data = [{'code': code, 'name': name} for code, name in ALGERIAN_WILAYAS]
        cache.set(key, data, WILAYA_TTL)
        return Response(data)


class UserRolesView(APIView):
    """
    GET /api/user-roles/
    
    Get list of user roles (admin only).
    """
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    def get(self, request):
        roles = [{'value': choice[0], 'label': choice[1]} for choice in UserRole.choices]
        return Response(roles)


class UserStatusesView(APIView):
    """
    GET /api/user-statuses/
    
    Get list of user statuses (admin only).
    """
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    def get(self, request):
        statuses = [{'value': choice[0], 'label': choice[1]} for choice in UserStatus.choices]
        return Response(statuses)


# =============================================================================
# ACCOUNT DELETION REQUEST VIEWS
# =============================================================================

class AccountDeletionRequestView(APIView):
    """
    User-facing account deletion request endpoint.
    
    GET  /api/auth/request-account-deletion/  — Check current request status
    POST /api/auth/request-account-deletion/  — Submit a new deletion request
    DELETE /api/auth/request-account-deletion/ — Cancel a pending request
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get the user's latest deletion request."""
        req = AccountDeletionRequest.objects.filter(
            user=request.user
        ).order_by('-created_at').first()

        if not req:
            return Response({'request': None})

        return Response({
            'request': AccountDeletionRequestSerializer(req).data
        })

    def post(self, request):
        """Submit a new deletion request. Only one active (PENDING) request is allowed."""
        # Check for existing pending request
        existing = AccountDeletionRequest.objects.filter(
            user=request.user,
            status=DeletionRequestStatus.PENDING
        ).exists()

        if existing:
            return Response(
                {'error': 'Vous avez déjà une demande de suppression en cours.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = AccountDeletionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)

        return Response({
            'message': 'Votre demande de suppression a été soumise. Un administrateur va la traiter.',
            'request': serializer.data
        }, status=status.HTTP_201_CREATED)

    def delete(self, request):
        """Cancel a pending deletion request."""
        req = AccountDeletionRequest.objects.filter(
            user=request.user,
            status=DeletionRequestStatus.PENDING
        ).first()

        if not req:
            return Response(
                {'error': 'Aucune demande en cours à annuler.'},
                status=status.HTTP_404_NOT_FOUND
            )

        req.delete()
        return Response({'message': 'Demande de suppression annulée.'})


class ConfirmAccountDeletionView(APIView):
    """
    POST /api/auth/confirm-account-deletion/
    
    Confirms account deletion after admin approval.
    Requires password. Performs full cascade delete.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import logging
        logger = logging.getLogger(__name__)

        serializer = ConfirmAccountDeletionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        password = serializer.validated_data['password']

        # Verify password
        if not user.check_password(password):
            return Response(
                {'error': 'Mot de passe incorrect.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for approved deletion request
        approved_req = AccountDeletionRequest.objects.filter(
            user=user,
            status=DeletionRequestStatus.APPROVED
        ).first()

        if not approved_req:
            return Response(
                {'error': 'Aucune demande de suppression approuvée trouvée.'},
                status=status.HTTP_403_FORBIDDEN
            )

        logger.info(f"[ACCOUNT-DELETE] Starting cascade deletion for user {user.email} (id={user.id})")

        try:
            # 1. Delete from Supabase Auth
            if user.supabase_id:
                try:
                    from .storage import get_supabase_client
                    supabase = get_supabase_client()
                    supabase.auth.admin.delete_user(str(user.supabase_id))
                    logger.info(f"[ACCOUNT-DELETE] Supabase Auth user deleted: {user.supabase_id}")
                except Exception as e:
                    logger.error(f"[ACCOUNT-DELETE] Supabase Auth deletion failed: {e}")
                    # Continue with Django deletion even if Supabase fails

            # 2. Delete avatar from Supabase Storage
            if user.avatar_url:
                try:
                    from .storage import delete_avatar
                    delete_avatar(user.avatar_url)
                    logger.info(f"[ACCOUNT-DELETE] Avatar deleted for user {user.id}")
                except Exception as e:
                    logger.error(f"[ACCOUNT-DELETE] Avatar deletion failed: {e}")

            # 3. Delete Django user (CASCADE handles all related objects):
            #    - Enrollments → LessonProgress, LessonNotes, QuizAttempts, FinalQuizAttempts
            #    - Orders → OrderItems
            #    - Certificates
            #    - ShareTokens
            #    - CourseRatings
            #    - PromoCodeUsages
            #    - CourseGifts (sent)
            #    - UserXP, XPTransactions, UserAchievements, LeaderboardCache
            #    - ReferralCode, Referrals
            #    - EmailVerificationTokens, PasswordResetTokens
            #    - AccountDeletionRequests
            #    - Courses created by user → instructor set to NULL (SET_NULL)
            user_email = user.email
            user.delete()
            logger.info(f"[ACCOUNT-DELETE] User {user_email} and all associated data deleted successfully")

            return Response({
                'message': 'Votre compte et toutes les données associées ont été supprimés définitivement.'
            })

        except Exception as e:
            logger.error(f"[ACCOUNT-DELETE] Cascade deletion failed for user {user.email}: {e}", exc_info=True)
            return Response(
                {'error': 'Une erreur est survenue lors de la suppression. Veuillez réessayer.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminDeletionRequestViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for account deletion requests.
    
    GET    /api/admin/deletion-requests/           — List all requests
    GET    /api/admin/deletion-requests/{id}/       — Detail
    POST   /api/admin/deletion-requests/{id}/approve/ — Approve
    POST   /api/admin/deletion-requests/{id}/reject/  — Reject
    """
    queryset = AccountDeletionRequest.objects.all().select_related(
        'user', 'reviewed_by'
    ).order_by('-created_at')
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    serializer_class = AdminDeletionRequestSerializer
    http_method_names = ['get', 'post', 'head', 'options']  # POST needed for approve/reject actions

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by status
        req_status = self.request.query_params.get('status')
        if req_status:
            queryset = queryset.filter(status=req_status)

        # Search by user email
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(user__email__icontains=search) |
                models.Q(user__first_name__icontains=search) |
                models.Q(user__last_name__icontains=search)
            )

        return queryset

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a deletion request."""
        from django.utils import timezone as tz

        deletion_req = self.get_object()

        if deletion_req.status != DeletionRequestStatus.PENDING:
            return Response(
                {'error': 'Cette demande a déjà été traitée.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = AdminDeletionRequestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        deletion_req.status = DeletionRequestStatus.APPROVED
        deletion_req.admin_notes = serializer.validated_data.get('admin_notes', '')
        deletion_req.reviewed_by = request.user
        deletion_req.reviewed_at = tz.now()
        deletion_req.save()

        return Response(AdminDeletionRequestSerializer(deletion_req).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a deletion request."""
        from django.utils import timezone as tz

        deletion_req = self.get_object()

        if deletion_req.status != DeletionRequestStatus.PENDING:
            return Response(
                {'error': 'Cette demande a déjà été traitée.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = AdminDeletionRequestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        deletion_req.status = DeletionRequestStatus.REJECTED
        deletion_req.admin_notes = serializer.validated_data.get('admin_notes', '')
        deletion_req.reviewed_by = request.user
        deletion_req.reviewed_at = tz.now()
        deletion_req.save()

        return Response(AdminDeletionRequestSerializer(deletion_req).data)


# =============================================================================
# NOTIFICATION VIEWS
# =============================================================================

class NotificationViewSet(viewsets.GenericViewSet):
    """
    GET  /api/auth/notifications/                   — List latest 30 notifications
    POST /api/auth/notifications/<uuid>/read/       — Mark one as read
    POST /api/auth/notifications/mark-all-read/     — Mark all as read
    """
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def list(self, request):
        qs = Notification.objects.filter(user=request.user).order_by('-created_at')[:30]
        return Response(NotificationSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        notif = get_object_or_404(Notification, pk=pk, user=request.user)
        if not notif.is_read:
            notif.is_read = True
            notif.save(update_fields=['is_read'])
        return Response({'status': 'ok'})

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'status': 'ok'})
