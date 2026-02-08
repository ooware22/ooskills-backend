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
from .storage import upload_avatar, delete_avatar, create_supabase_auth_user
from .email import send_verification_email


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
    avatar = serializers.ImageField(required=False, allow_null=True, write_only=True)
    
    class Meta:
        model = User
        fields = [
            'email', 'password', 'password_confirm',
            'first_name', 'last_name', 'phone', 'wilaya',
            'referral_code', 'newsletter_subscribed', 'avatar'
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
    
    def validate_avatar(self, value):
        """Validate avatar file size and type."""
        if value:
            max_size = 5 * 1024 * 1024
            if value.size > max_size:
                raise serializers.ValidationError(
                    "La taille du fichier ne doit pas dépasser 5 Mo."
                )
            allowed_extensions = ['jpg', 'jpeg', 'png', 'webp', 'gif']
            file_extension = value.name.split('.')[-1].lower()
            if file_extension not in allowed_extensions:
                raise serializers.ValidationError(
                    f"Format non supporté. Formats acceptés: {', '.join(allowed_extensions)}"
                )
        return value
    
    def create(self, validated_data):
        referral_code_str = validated_data.pop('referral_code', None)
        avatar_file = validated_data.pop('avatar', None)
        email = validated_data.get('email')
        password = validated_data.get('password')
        
        # Create user in Supabase Auth first
        try:
            user_metadata = {
                'first_name': validated_data.get('first_name', ''),
                'last_name': validated_data.get('last_name', ''),
            }
            supabase_user = create_supabase_auth_user(
                email=email,
                password=password,
                user_metadata=user_metadata
            )
            supabase_id = supabase_user['id']
        except Exception as e:
            raise serializers.ValidationError({
                'email': f"Erreur lors de la création du compte: {str(e)}"
            })
        
        # Create Django user
        user = User.objects.create_user(
            email=email,
            password=password,
            supabase_id=supabase_id,
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
        
        # Upload avatar to Supabase in background (non-blocking)
        if avatar_file:
            try:
                avatar_file.seek(0)
                # Read file content into memory before the request ends
                file_content = avatar_file.read()
                file_name = avatar_file.name
                user_id = str(user.id)
                
                import threading
                def _upload_avatar():
                    try:
                        from .storage import get_supabase_client
                        supabase = get_supabase_client()
                        file_ext = file_name.split('.')[-1].lower()
                        path = f"avatars/{user_id}.{file_ext}"
                        content_types = {
                            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                            'png': 'image/png', 'webp': 'image/webp', 'gif': 'image/gif',
                        }
                        supabase.storage.from_('avatars').upload(
                            path=path, file=file_content,
                            file_options={'content-type': content_types.get(file_ext, 'image/jpeg'), 'upsert': 'true'}
                        )
                        public_url = supabase.storage.from_('avatars').get_public_url(path)
                        from .models import User as UserModel
                        UserModel.objects.filter(id=user_id).update(avatar_url=public_url)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).error(f"Avatar upload failed for user {user_id}: {e}")
                
                threading.Thread(target=_upload_avatar, daemon=True).start()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Avatar read failed for user {user.id}: {e}")
        
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
    """Serializer for updating user profile with Supabase avatar upload."""
    
    avatar = serializers.ImageField(required=False, allow_null=True, write_only=True)
    
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
    
    def validate_avatar(self, value):
        """Validate avatar file size and type."""
        if value:
            # Check file size (max 5MB)
            max_size = 5 * 1024 * 1024
            if value.size > max_size:
                raise serializers.ValidationError(
                    "La taille du fichier ne doit pas dépasser 5 Mo."
                )
            # Check file extension
            allowed_extensions = ['jpg', 'jpeg', 'png', 'webp', 'gif']
            file_extension = value.name.split('.')[-1].lower()
            if file_extension not in allowed_extensions:
                raise serializers.ValidationError(
                    f"Format non supporté. Formats acceptés: {', '.join(allowed_extensions)}"
                )
        return value
    
    def update(self, instance, validated_data):
        """Handle avatar upload to Supabase Storage."""
        avatar_file = validated_data.pop('avatar', None)
        
        # Upload avatar to Supabase if provided
        if avatar_file:
            # Delete old avatar if exists
            if instance.avatar_url:
                delete_avatar(instance.avatar_url)
            
            # Upload new avatar
            public_url = upload_avatar(avatar_file, str(instance.id))
            instance.avatar_url = public_url
        
        # Update other fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        instance.save()
        return instance


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
    """Serializer for admin to create users with Supabase avatar upload."""
    
    password = serializers.CharField(
        write_only=True,
        required=False,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    avatar = serializers.ImageField(required=False, allow_null=True, write_only=True)
    
    class Meta:
        model = User
        fields = [
            'email', 'password', 'first_name', 'last_name',
            'phone', 'wilaya', 'role', 'status',
            'is_staff', 'email_verified', 'avatar',
            'language', 'newsletter_subscribed'
        ]
    
    def validate_avatar(self, value):
        """Validate avatar file size and type."""
        if value:
            max_size = 5 * 1024 * 1024
            if value.size > max_size:
                raise serializers.ValidationError(
                    "La taille du fichier ne doit pas dépasser 5 Mo."
                )
            allowed_extensions = ['jpg', 'jpeg', 'png', 'webp', 'gif']
            file_extension = value.name.split('.')[-1].lower()
            if file_extension not in allowed_extensions:
                raise serializers.ValidationError(
                    f"Format non supporté. Formats acceptés: {', '.join(allowed_extensions)}"
                )
        return value
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        avatar_file = validated_data.pop('avatar', None)
        email = validated_data.get('email')
        
        # Create user in Supabase Auth first
        try:
            user_metadata = {
                'first_name': validated_data.get('first_name', ''),
                'last_name': validated_data.get('last_name', ''),
            }
            supabase_user = create_supabase_auth_user(
                email=email,
                password=password,
                user_metadata=user_metadata
            )
            validated_data['supabase_id'] = supabase_user['id']
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Supabase user creation failed for {email}: {str(e)}")
            raise serializers.ValidationError({
                'email': f"Erreur lors de la création du compte: {str(e)}"
            })
        
        # Create Django user
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        
        # Upload avatar to Supabase in background (non-blocking)
        if avatar_file:
            try:
                avatar_file.seek(0)
                file_content = avatar_file.read()
                file_name = avatar_file.name
                user_id = str(user.id)
                
                import threading
                def _upload_avatar():
                    try:
                        from .storage import get_supabase_client
                        supabase = get_supabase_client()
                        file_ext = file_name.split('.')[-1].lower()
                        path = f"avatars/{user_id}.{file_ext}"
                        content_types = {
                            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                            'png': 'image/png', 'webp': 'image/webp', 'gif': 'image/gif',
                        }
                        supabase.storage.from_('avatars').upload(
                            path=path, file=file_content,
                            file_options={'content-type': content_types.get(file_ext, 'image/jpeg'), 'upsert': 'true'}
                        )
                        public_url = supabase.storage.from_('avatars').get_public_url(path)
                        User.objects.filter(id=user_id).update(avatar_url=public_url)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).error(f"Avatar upload failed for admin-created user {user_id}: {e}")
                
                threading.Thread(target=_upload_avatar, daemon=True).start()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Avatar read failed for admin-created user {user.id}: {e}")
        
        # Send verification email in background (non-blocking)
        import threading
        threading.Thread(target=send_verification_email, args=(user,), daemon=True).start()
        
        return user



class AdminUserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for admin to update users with Supabase avatar upload."""
    
    avatar = serializers.ImageField(required=False, allow_null=True, write_only=True)
    
    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name',
            'phone', 'wilaya', 'role', 'status',
            'is_staff', 'is_active', 'email_verified', 'avatar',
            'language', 'newsletter_subscribed'
        ]
    
    def validate_avatar(self, value):
        """Validate avatar file size and type."""
        if value:
            max_size = 5 * 1024 * 1024
            if value.size > max_size:
                raise serializers.ValidationError(
                    "La taille du fichier ne doit pas dépasser 5 Mo."
                )
            allowed_extensions = ['jpg', 'jpeg', 'png', 'webp', 'gif']
            file_extension = value.name.split('.')[-1].lower()
            if file_extension not in allowed_extensions:
                raise serializers.ValidationError(
                    f"Format non supporté. Formats acceptés: {', '.join(allowed_extensions)}"
                )
        return value
    
    def update(self, instance, validated_data):
        """Handle avatar upload to Supabase Storage."""
        avatar_file = validated_data.pop('avatar', None)
        
        # Upload avatar to Supabase if provided
        if avatar_file:
            # Delete old avatar if exists
            if instance.avatar_url:
                delete_avatar(instance.avatar_url)
            
            # Upload new avatar
            public_url = upload_avatar(avatar_file, str(instance.id))
            instance.avatar_url = public_url
        
        # Update other fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        instance.save()
        return instance


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
