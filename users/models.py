"""
User Model for OOSkills Platform

Supports both:
- Local Django authentication
- Supabase Auth integration (UUID-based)

Based on Cahier des Charges specifications:
- UserRole: USER, INSTRUCTOR, ADMIN, SUPER_ADMIN
- UserStatus: PENDING, ACTIVE, SUSPENDED, DELETED
- Fields: id, email, name, role, status, wilaya, phone, avatar
"""

import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator


# =============================================================================
# ENUMERATIONS
# =============================================================================

class UserRole(models.TextChoices):
    """User roles as defined in the cahier des charges."""
    USER = 'USER', 'Utilisateur'
    INSTRUCTOR = 'INSTRUCTOR', 'Formateur'
    ADMIN = 'ADMIN', 'Administrateur'
    SUPER_ADMIN = 'SUPER_ADMIN', 'Super Administrateur'


class UserStatus(models.TextChoices):
    """User account status."""
    PENDING = 'PENDING', 'En attente'
    ACTIVE = 'ACTIVE', 'Actif'
    SUSPENDED = 'SUSPENDED', 'Suspendu'
    DELETED = 'DELETED', 'Supprimé'


# =============================================================================
# ALGERIAN WILAYAS
# =============================================================================

ALGERIAN_WILAYAS = [
    ('01', 'Adrar'),
    ('02', 'Chlef'),
    ('03', 'Laghouat'),
    ('04', 'Oum El Bouaghi'),
    ('05', 'Batna'),
    ('06', 'Béjaïa'),
    ('07', 'Biskra'),
    ('08', 'Béchar'),
    ('09', 'Blida'),
    ('10', 'Bouira'),
    ('11', 'Tamanrasset'),
    ('12', 'Tébessa'),
    ('13', 'Tlemcen'),
    ('14', 'Tiaret'),
    ('15', 'Tizi Ouzou'),
    ('16', 'Alger'),
    ('17', 'Djelfa'),
    ('18', 'Jijel'),
    ('19', 'Sétif'),
    ('20', 'Saïda'),
    ('21', 'Skikda'),
    ('22', 'Sidi Bel Abbès'),
    ('23', 'Annaba'),
    ('24', 'Guelma'),
    ('25', 'Constantine'),
    ('26', 'Médéa'),
    ('27', 'Mostaganem'),
    ('28', "M'Sila"),
    ('29', 'Mascara'),
    ('30', 'Ouargla'),
    ('31', 'Oran'),
    ('32', 'El Bayadh'),
    ('33', 'Illizi'),
    ('34', 'Bordj Bou Arréridj'),
    ('35', 'Boumerdès'),
    ('36', 'El Tarf'),
    ('37', 'Tindouf'),
    ('38', 'Tissemsilt'),
    ('39', 'El Oued'),
    ('40', 'Khenchela'),
    ('41', 'Souk Ahras'),
    ('42', 'Tipaza'),
    ('43', 'Mila'),
    ('44', 'Aïn Defla'),
    ('45', 'Naâma'),
    ('46', 'Aïn Témouchent'),
    ('47', 'Ghardaïa'),
    ('48', 'Relizane'),
    ('49', "El M'Ghair"),
    ('50', 'El Meniaa'),
    ('51', 'Ouled Djellal'),
    ('52', 'Bordj Badji Mokhtar'),
    ('53', 'Béni Abbès'),
    ('54', 'Timimoun'),
    ('55', 'Touggourt'),
    ('56', 'Djanet'),
    ('57', 'In Salah'),
    ('58', 'In Guezzam'),
]


# =============================================================================
# USER MANAGER
# =============================================================================

class UserManager(BaseUserManager):
    """
    Custom user manager supporting UUID primary keys and Supabase Auth integration.
    """
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular user."""
        if not email:
            raise ValueError('L\'adresse email est obligatoire')
        
        email = self.normalize_email(email)
        extra_fields.setdefault('role', UserRole.USER)
        extra_fields.setdefault('status', UserStatus.PENDING)
        
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()  # For Supabase Auth users
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser."""
        extra_fields.setdefault('role', UserRole.SUPER_ADMIN)
        extra_fields.setdefault('status', UserStatus.ACTIVE)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('email_verified', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)
    
    def get_by_supabase_id(self, supabase_id):
        """Get user by their Supabase Auth UUID."""
        return self.get(supabase_id=supabase_id)
    
    def get_or_create_from_supabase(self, supabase_user_data):
        """
        Get or create a user from Supabase Auth data.
        
        Args:
            supabase_user_data: Dict containing Supabase user info
                {
                    'id': 'uuid-string',
                    'email': 'user@example.com',
                    'user_metadata': {'full_name': '...', 'avatar_url': '...'}
                }
        """
        supabase_id = supabase_user_data.get('id')
        email = supabase_user_data.get('email')
        metadata = supabase_user_data.get('user_metadata', {})
        
        try:
            user = self.get(supabase_id=supabase_id)
            # Update email if changed
            if user.email != email:
                user.email = email
                user.save(update_fields=['email'])
            return user, False
        except self.model.DoesNotExist:
            # Check if user exists by email (migration case)
            try:
                user = self.get(email=email)
                user.supabase_id = supabase_id
                user.save(update_fields=['supabase_id'])
                return user, False
            except self.model.DoesNotExist:
                pass
            
            # Create new user
            user = self.create_user(
                email=email,
                supabase_id=supabase_id,
                first_name=metadata.get('full_name', '').split(' ')[0] if metadata.get('full_name') else '',
                last_name=' '.join(metadata.get('full_name', '').split(' ')[1:]) if metadata.get('full_name') else '',
                avatar_url=metadata.get('avatar_url'),
                email_verified=True,
                status=UserStatus.ACTIVE,
            )
            return user, True


# =============================================================================
# USER MODEL
# =============================================================================

class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model for OOSkills platform.
    
    Supports both:
    - Local Django authentication (email/password)
    - Supabase Auth integration (UUID-based, OAuth)
    
    Uses UUID as primary key for Supabase compatibility.
    """
    
    # Primary key - UUID for Supabase compatibility
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    
    # Supabase Auth integration
    supabase_id = models.UUIDField(
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="UUID from Supabase Auth (auth.users.id)"
    )
    
    # Authentication fields
    email = models.EmailField(
        'Adresse email',
        unique=True,
        db_index=True
    )
    email_verified = models.BooleanField(
        'Email vérifié',
        default=False
    )
    
    # Profile fields
    first_name = models.CharField(
        'Prénom',
        max_length=150,
        blank=True
    )
    last_name = models.CharField(
        'Nom',
        max_length=150,
        blank=True
    )
    
    # Phone with Algerian format validation
    phone_regex = RegexValidator(
        regex=r'^(\+213|0)(5|6|7)[0-9]{8}$',
        message="Le numéro doit être au format: '+213XXXXXXXXX' ou '0XXXXXXXXX'"
    )
    phone = models.CharField(
        'Téléphone',
        validators=[phone_regex],
        max_length=15,
        blank=True
    )
    
    # Location
    wilaya = models.CharField(
        'Wilaya',
        max_length=2,
        choices=ALGERIAN_WILAYAS,
        blank=True
    )
    
    # Avatar
    avatar = models.ImageField(
        'Photo de profil',
        upload_to='avatars/',
        null=True,
        blank=True
    )
    avatar_url = models.URLField(
        'URL avatar externe',
        max_length=500,
        null=True,
        blank=True,
        help_text="URL from OAuth provider (Google, Facebook)"
    )
    
    # Role and Status (from cahier des charges)
    role = models.CharField(
        'Rôle',
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.USER,
        db_index=True
    )
    status = models.CharField(
        'Statut',
        max_length=20,
        choices=UserStatus.choices,
        default=UserStatus.PENDING,
        db_index=True
    )
    
    # Django admin permissions
    is_staff = models.BooleanField(
        'Accès admin',
        default=False,
        help_text="Autorise l'accès à l'interface d'administration Django."
    )
    is_active = models.BooleanField(
        'Compte actif',
        default=True,
        help_text="Indique si l'utilisateur peut se connecter."
    )
    
    # Timestamps
    date_joined = models.DateTimeField(
        'Date d\'inscription',
        default=timezone.now
    )
    last_login = models.DateTimeField(
        'Dernière connexion',
        null=True,
        blank=True
    )
    updated_at = models.DateTimeField(
        'Dernière modification',
        auto_now=True
    )
    
    # Preferences
    language = models.CharField(
        'Langue préférée',
        max_length=2,
        choices=[('fr', 'Français'), ('ar', 'العربية'), ('en', 'English')],
        default='fr'
    )
    
    # Marketing
    newsletter_subscribed = models.BooleanField(
        'Abonné newsletter',
        default=False
    )
    
    # Manager
    objects = UserManager()
    
    # Auth config
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # email is already required by USERNAME_FIELD
    
    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'
        ordering = ['-date_joined']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['supabase_id']),
            models.Index(fields=['role', 'status']),
        ]
    
    def __str__(self):
        return self.email
    
    # ==========================================================================
    # PROPERTIES
    # ==========================================================================
    
    @property
    def full_name(self):
        """Return full name or email if name not set."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.email.split('@')[0]
    
    @property
    def display_name(self):
        """Return display name for UI."""
        if self.first_name:
            return self.first_name
        return self.email.split('@')[0]
    
    @property
    def avatar_display_url(self):
        """Return avatar URL (uploaded file or external URL)."""
        if self.avatar:
            return self.avatar.url
        return self.avatar_url
    
    @property
    def is_admin(self):
        """Check if user has admin privileges."""
        return self.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]
    
    @property
    def is_super_admin(self):
        """Check if user is super admin."""
        return self.role == UserRole.SUPER_ADMIN
    
    @property
    def is_instructor(self):
        """Check if user is an instructor."""
        return self.role == UserRole.INSTRUCTOR
    
    @property
    def wilaya_name(self):
        """Get wilaya display name."""
        return dict(ALGERIAN_WILAYAS).get(self.wilaya, '')
    
    # ==========================================================================
    # METHODS
    # ==========================================================================
    
    def get_short_name(self):
        """Return short name for display."""
        return self.first_name or self.email.split('@')[0]
    
    def activate(self):
        """Activate user account."""
        self.status = UserStatus.ACTIVE
        self.is_active = True
        self.save(update_fields=['status', 'is_active', 'updated_at'])
    
    def suspend(self):
        """Suspend user account."""
        self.status = UserStatus.SUSPENDED
        self.is_active = False
        self.save(update_fields=['status', 'is_active', 'updated_at'])
    
    def soft_delete(self):
        """Soft delete user account."""
        self.status = UserStatus.DELETED
        self.is_active = False
        self.save(update_fields=['status', 'is_active', 'updated_at'])
    
    def promote_to_admin(self):
        """Promote user to admin role."""
        self.role = UserRole.ADMIN
        self.is_staff = True
        self.save(update_fields=['role', 'is_staff', 'updated_at'])
    
    def promote_to_instructor(self):
        """Promote user to instructor role."""
        self.role = UserRole.INSTRUCTOR
        self.save(update_fields=['role', 'updated_at'])


# =============================================================================
# REFERRAL CODE MODEL
# =============================================================================

class ReferralCode(models.Model):
    """
    User referral codes for the parrainage system.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='referral_code'
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True
    )
    uses_count = models.PositiveIntegerField(default=0)
    reward_earned = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Code de parrainage'
        verbose_name_plural = 'Codes de parrainage'
    
    def __str__(self):
        return f"{self.code} ({self.user.email})"
    
    @classmethod
    def generate_code(cls, user):
        """Generate a unique referral code for user."""
        import random
        import string
        
        # Generate code based on user's name + random chars
        base = user.first_name[:3].upper() if user.first_name else 'OOS'
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        code = f"{base}{suffix}"
        
        # Ensure uniqueness
        while cls.objects.filter(code=code).exists():
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
            code = f"{base}{suffix}"
        
        return cls.objects.create(user=user, code=code)


class Referral(models.Model):
    """
    Track referral relationships between users.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    referrer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='referrals_made'
    )
    referred = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='referred_by'
    )
    referral_code = models.ForeignKey(
        ReferralCode,
        on_delete=models.CASCADE,
        related_name='referrals'
    )
    reward_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )
    reward_paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Parrainage'
        verbose_name_plural = 'Parrainages'
    
    def __str__(self):
        return f"{self.referrer.email} → {self.referred.email}"
