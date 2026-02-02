"""
User Serializers for OOSkills Platform

Provides serializers for:
- User registration
- User login
- User profile (read/update)
- Admin user management
- Referral system
"""

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from .models import User, UserRole, UserStatus, ReferralCode, Referral, ALGERIAN_WILAYAS


# =============================================================================
# AUTHENTICATION SERIALIZERS
# =============================================================================

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT serializer that uses email instead of username
    and properly validates the password.
    """
    username_field = 'email'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Replace 'username' field with 'email'
        self.fields['email'] = serializers.EmailField(required=True)
        self.fields['password'] = serializers.CharField(
            write_only=True,
            required=True,
            style={'input_type': 'password'}
        )
        # Remove the default username field if it exists
        if 'username' in self.fields:
            del self.fields['username']
    
    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        
        if not email or not password:
            raise serializers.ValidationError({
                'detail': 'Email et mot de passe sont obligatoires.'
            })
        
        # Check if user exists
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({
                'detail': 'Email ou mot de passe incorrect.'
            })
        
        # Check if user account is active
        if user.status == UserStatus.DELETED:
            raise serializers.ValidationError({
                'detail': 'Ce compte a été supprimé.'
            })
        
        if user.status == UserStatus.SUSPENDED:
            raise serializers.ValidationError({
                'detail': 'Ce compte a été suspendu.'
            })
        
        # Authenticate user (checks password)
        authenticated_user = authenticate(
            request=self.context.get('request'),
            email=email,
            password=password
        )
        
        if authenticated_user is None:
            raise serializers.ValidationError({
                'detail': 'Email ou mot de passe incorrect.'
            })
        
        if not authenticated_user.is_active:
            raise serializers.ValidationError({
                'detail': 'Ce compte est désactivé.'
            })
        
        # Generate tokens
        refresh = self.get_token(authenticated_user)
        
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': str(authenticated_user.id),
                'email': authenticated_user.email,
                'first_name': authenticated_user.first_name,
                'last_name': authenticated_user.last_name,
                'role': authenticated_user.role,
                'status': authenticated_user.status,
            }
        }


# =============================================================================
# PUBLIC SERIALIZERS
# =============================================================================

class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration."""
    
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    referral_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True
    )
    
    class Meta:
        model = User
        fields = [
            'email', 'password', 'password_confirm',
            'first_name', 'last_name', 'phone', 'wilaya',
            'referral_code', 'newsletter_subscribed'
        ]
    
    def validate(self, attrs):
        if attrs['password'] != attrs.pop('password_confirm'):
            raise serializers.ValidationError({
                'password_confirm': "Les mots de passe ne correspondent pas."
            })
        return attrs
    
    def validate_referral_code(self, value):
        if value:
            try:
                ReferralCode.objects.get(code=value, is_active=True)
            except ReferralCode.DoesNotExist:
                raise serializers.ValidationError("Code de parrainage invalide.")
        return value
    
    def create(self, validated_data):
        referral_code_str = validated_data.pop('referral_code', None)
        
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            phone=validated_data.get('phone', ''),
            wilaya=validated_data.get('wilaya', ''),
            newsletter_subscribed=validated_data.get('newsletter_subscribed', False),
        )
        
        # Handle referral
        if referral_code_str:
            try:
                ref_code = ReferralCode.objects.get(code=referral_code_str, is_active=True)
                Referral.objects.create(
                    referrer=ref_code.user,
                    referred=user,
                    referral_code=ref_code
                )
                ref_code.uses_count += 1
                ref_code.save(update_fields=['uses_count'])
            except ReferralCode.DoesNotExist:
                pass
        
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile (read/update)."""
    
    wilaya_name = serializers.ReadOnlyField()
    full_name = serializers.ReadOnlyField()
    display_name = serializers.ReadOnlyField()
    avatar_display_url = serializers.ReadOnlyField()
    referral_code = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name', 'display_name',
            'phone', 'wilaya', 'wilaya_name',
            'avatar', 'avatar_url', 'avatar_display_url',
            'role', 'status', 'email_verified',
            'language', 'newsletter_subscribed',
            'date_joined', 'last_login',
            'referral_code'
        ]
        read_only_fields = [
            'id', 'email', 'role', 'status', 'email_verified',
            'date_joined', 'last_login'
        ]
    
    def get_referral_code(self, obj):
        try:
            return obj.referral_code.code
        except ReferralCode.DoesNotExist:
            return None


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile."""
    
    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'phone', 'wilaya',
            'avatar', 'language', 'newsletter_subscribed'
        ]
    
    def validate_phone(self, value):
        if value and not value.startswith(('+213', '0')):
            raise serializers.ValidationError(
                "Le numéro doit commencer par +213 ou 0"
            )
        return value


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for password change."""
    
    old_password = serializers.CharField(required=True, style={'input_type': 'password'})
    new_password = serializers.CharField(
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    new_password_confirm = serializers.CharField(required=True, style={'input_type': 'password'})
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                'new_password_confirm': "Les mots de passe ne correspondent pas."
            })
        return attrs
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Mot de passe actuel incorrect.")
        return value


# =============================================================================
# ADMIN SERIALIZERS
# =============================================================================

class AdminUserSerializer(serializers.ModelSerializer):
    """Full user serializer for admin operations."""
    
    wilaya_name = serializers.ReadOnlyField()
    full_name = serializers.ReadOnlyField()
    avatar_display_url = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = [
            'id', 'supabase_id', 'email', 'email_verified',
            'first_name', 'last_name', 'full_name',
            'phone', 'wilaya', 'wilaya_name',
            'avatar', 'avatar_url', 'avatar_display_url',
            'role', 'status', 'is_staff', 'is_active',
            'language', 'newsletter_subscribed',
            'date_joined', 'last_login', 'updated_at'
        ]
        read_only_fields = ['id', 'supabase_id', 'date_joined', 'last_login', 'updated_at']


class AdminUserCreateSerializer(serializers.ModelSerializer):
    """Serializer for admin to create users."""
    
    password = serializers.CharField(
        write_only=True,
        required=False,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    
    class Meta:
        model = User
        fields = [
            'email', 'password', 'first_name', 'last_name',
            'phone', 'wilaya', 'role', 'status',
            'is_staff', 'email_verified'
        ]
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for admin to update users."""
    
    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name',
            'phone', 'wilaya', 'role', 'status',
            'is_staff', 'is_active', 'email_verified'
        ]


# =============================================================================
# REFERRAL SERIALIZERS
# =============================================================================

class ReferralCodeSerializer(serializers.ModelSerializer):
    """Serializer for referral codes."""
    
    user_email = serializers.EmailField(source='user.email', read_only=True)
    
    class Meta:
        model = ReferralCode
        fields = ['id', 'code', 'user_email', 'uses_count', 'reward_earned', 'is_active', 'created_at']
        read_only_fields = ['id', 'code', 'uses_count', 'reward_earned', 'created_at']


class ReferralSerializer(serializers.ModelSerializer):
    """Serializer for referral relationships."""
    
    referrer_email = serializers.EmailField(source='referrer.email', read_only=True)
    referred_email = serializers.EmailField(source='referred.email', read_only=True)
    
    class Meta:
        model = Referral
        fields = [
            'id', 'referrer', 'referrer_email',
            'referred', 'referred_email',
            'referral_code', 'reward_amount', 'reward_paid',
            'created_at'
        ]
        read_only_fields = ['id', 'referrer', 'referred', 'referral_code', 'created_at']


# =============================================================================
# COMPACT SERIALIZERS (for nested use)
# =============================================================================

class UserCompactSerializer(serializers.ModelSerializer):
    """Compact user serializer for nested use in other serializers."""
    
    display_name = serializers.ReadOnlyField()
    avatar_display_url = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = ['id', 'email', 'display_name', 'avatar_display_url', 'role']


class WilayaSerializer(serializers.Serializer):
    """Serializer for wilaya choices."""
    
    code = serializers.CharField()
    name = serializers.CharField()
    
    @classmethod
    def get_all_wilayas(cls):
        return [{'code': code, 'name': name} for code, name in ALGERIAN_WILAYAS]
