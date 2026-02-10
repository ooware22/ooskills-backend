"""
User Views for OOSkills Platform

Provides endpoints for:
- Authentication (register, login, password reset)
- User profile management
- Admin user management
- Referral system
"""

from django.db import models
from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import update_session_auth_hash

from .storage import upload_avatar, delete_avatar
from .avatar_serializer import AvatarUploadSerializer
from .email import send_verification_email, verify_email_token, send_password_reset_email, verify_password_reset_token

from .models import User, UserRole, UserStatus, AuthProvider, ReferralCode, Referral, ALGERIAN_WILAYAS
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
    authentication_classes = []  # Skip all auth for this public endpoint
    serializer_class = UserRegistrationSerializer
    parser_classes = [MultiPartParser, FormParser]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Send verification email in background (non-blocking)
        import threading
        threading.Thread(target=send_verification_email, args=(user,), daemon=True).start()
        
        # Generate JWT tokens for the new user
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': UserProfileSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
            'message': 'Inscription réussie. Veuillez vérifier votre email.'
        }, status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    """
    POST /api/auth/verify-email/
    
    Verify user email with token.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Skip all auth for this public endpoint
    
    def post(self, request):
        import time
        start = time.time()
        print(f"[VERIFY-EMAIL] START")
        
        token = request.data.get('token')
        print(f"[VERIFY-EMAIL] Token extracted: {bool(token)} ({time.time()-start:.2f}s)")
        
        if not token:
            return Response({
                'error': 'Token requis.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        success, user, message = verify_email_token(token)
        print(f"[VERIFY-EMAIL] verify_email_token done: success={success} ({time.time()-start:.2f}s)")
        
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


class ProfileView(generics.RetrieveUpdateAPIView):
    """
    GET /api/auth/me/
    PATCH /api/auth/me/
    
    Get or update current user's profile.
    Supports multipart/form-data for avatar upload.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
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
    
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        
        try:
            user = User.objects.get(email=email)
            
            # Only send if user account is not deleted
            if user.status != UserStatus.DELETED:
                # Send reset email in background (non-blocking)
                import threading
                threading.Thread(
                    target=send_password_reset_email,
                    args=(user,),
                    daemon=True
                ).start()
        except User.DoesNotExist:
            pass  # Don't reveal if email exists
        
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
    
    Logout user (stateless JWT - client should discard tokens).
    Note: With stateless JWT, tokens cannot be invalidated server-side.
    The client is responsible for discarding tokens on logout.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        # Stateless JWT: No server-side invalidation
        # Client should discard access and refresh tokens
        return Response({
            'message': 'Déconnexion réussie.',
            'detail': 'Veuillez supprimer les tokens côté client.'
        })


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
        
        return Response({
            'user': UserProfileSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
            'message': 'Social login successful.'
        })
    
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
    
    Get list of Algerian wilayas.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        wilayas = [{'code': code, 'name': name} for code, name in ALGERIAN_WILAYAS]
        return Response(wilayas)


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
