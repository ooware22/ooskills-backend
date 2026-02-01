"""
User Admin Configuration for OOSkills Platform
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User, UserRole, UserStatus, ReferralCode, Referral


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom admin for User model with UUID support."""
    
    list_display = [
        'email', 'full_name', 'role_badge', 'status_badge', 
        'wilaya_name', 'email_verified', 'date_joined'
    ]
    list_filter = ['role', 'status', 'email_verified', 'wilaya', 'is_staff', 'is_active']
    search_fields = ['email', 'first_name', 'last_name', 'phone']
    ordering = ['-date_joined']
    readonly_fields = ['id', 'supabase_id', 'date_joined', 'last_login', 'updated_at']
    
    fieldsets = (
        (None, {
            'fields': ('id', 'email', 'password')
        }),
        ('Informations personnelles', {
            'fields': ('first_name', 'last_name', 'phone', 'wilaya', 'avatar', 'avatar_url')
        }),
        ('Rôle et Statut', {
            'fields': ('role', 'status', 'email_verified')
        }),
        ('Supabase Auth', {
            'fields': ('supabase_id',),
            'classes': ('collapse',),
        }),
        ('Permissions Django', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',),
        }),
        ('Préférences', {
            'fields': ('language', 'newsletter_subscribed'),
        }),
        ('Dates', {
            'fields': ('date_joined', 'last_login', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'first_name', 'last_name', 'role'),
        }),
    )
    
    def role_badge(self, obj):
        """Display role with colored badge."""
        colors = {
            UserRole.SUPER_ADMIN: '#dc2626',  # red
            UserRole.ADMIN: '#ea580c',  # orange
            UserRole.INSTRUCTOR: '#2563eb',  # blue
            UserRole.USER: '#6b7280',  # gray
        }
        color = colors.get(obj.role, '#6b7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color, obj.get_role_display()
        )
    role_badge.short_description = 'Rôle'
    role_badge.admin_order_field = 'role'
    
    def status_badge(self, obj):
        """Display status with colored badge."""
        colors = {
            UserStatus.ACTIVE: '#16a34a',  # green
            UserStatus.PENDING: '#ca8a04',  # yellow
            UserStatus.SUSPENDED: '#dc2626',  # red
            UserStatus.DELETED: '#6b7280',  # gray
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Statut'
    status_badge.admin_order_field = 'status'
    
    actions = ['activate_users', 'suspend_users', 'promote_to_admin']
    
    @admin.action(description="Activer les utilisateurs sélectionnés")
    def activate_users(self, request, queryset):
        count = queryset.update(status=UserStatus.ACTIVE, is_active=True)
        self.message_user(request, f"{count} utilisateur(s) activé(s).")
    
    @admin.action(description="Suspendre les utilisateurs sélectionnés")
    def suspend_users(self, request, queryset):
        count = queryset.update(status=UserStatus.SUSPENDED, is_active=False)
        self.message_user(request, f"{count} utilisateur(s) suspendu(s).")
    
    @admin.action(description="Promouvoir en administrateur")
    def promote_to_admin(self, request, queryset):
        count = queryset.update(role=UserRole.ADMIN, is_staff=True)
        self.message_user(request, f"{count} utilisateur(s) promu(s) administrateur.")


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    """Admin for referral codes."""
    list_display = ['code', 'user', 'uses_count', 'reward_earned', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['code', 'user__email']
    readonly_fields = ['uses_count', 'reward_earned', 'created_at']


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    """Admin for referrals."""
    list_display = ['referrer', 'referred', 'referral_code', 'reward_amount', 'reward_paid', 'created_at']
    list_filter = ['reward_paid', 'created_at']
    search_fields = ['referrer__email', 'referred__email', 'referral_code__code']
    readonly_fields = ['created_at']
