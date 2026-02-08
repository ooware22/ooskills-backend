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
from .email import send_verification_email, verify_email_token

from .models import User, UserRole, UserStatus, ReferralCode, Referral, ALGERIAN_WILAYAS
from .serializers import (
    UserRegistrationSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    ChangePasswordSerializer,
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
