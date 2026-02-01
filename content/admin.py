"""
Landing Page CMS Django Admin Configuration

Provides a user-friendly admin interface for managing landing page content.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
import json

from .models import (
    HeroSection, FeaturesSection, FeatureItem,
    Partner, FAQItem, Testimonial
)


# =============================================================================
# INLINE ADMINS
# =============================================================================

class FeatureItemInline(admin.TabularInline):
    """Inline admin for Feature items within Features Section."""
    model = FeatureItem
    extra = 1
    ordering = ['order']
    fields = ['order', 'icon', 'title', 'description', 'is_active']
    

# =============================================================================
# MODEL ADMINS
# =============================================================================

@admin.register(HeroSection)
class HeroSectionAdmin(admin.ModelAdmin):
    """Admin for Hero Section."""
    list_display = ['id', 'get_title_preview', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['title', 'subtitle', 'description']
    list_editable = ['is_active']
    readonly_fields = ['created_at', 'updated_at', 'background_preview']
    
    fieldsets = (
        ('Content', {
            'fields': ('title', 'subtitle', 'description'),
            'description': 'Enter translations as JSON: {"fr": "...", "ar": "...", "en": "..."}'
        }),
        ('Background', {
            'fields': ('background_image', 'background_image_url', 'background_preview'),
        }),
        ('Status', {
            'fields': ('is_active',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def get_title_preview(self, obj):
        """Display a preview of the title."""
        title = obj.get_translated_value(obj.title, 'en')
        return title[:50] + '...' if len(title) > 50 else title
    get_title_preview.short_description = 'Title'
    
    def background_preview(self, obj):
        """Display background image preview."""
        url = obj.get_background_url()
        if url:
            return format_html('<img src="{}" style="max-height: 100px; max-width: 200px;" />', url)
        return 'No image'
    background_preview.short_description = 'Preview'


@admin.register(FeaturesSection)
class FeaturesSectionAdmin(admin.ModelAdmin):
    """Admin for Features Section."""
    list_display = ['id', 'get_title_preview', 'items_count', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['title', 'subtitle']
    list_editable = ['is_active']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [FeatureItemInline]
    
    fieldsets = (
        ('Content', {
            'fields': ('title', 'subtitle'),
            'description': 'Enter translations as JSON: {"fr": "...", "ar": "...", "en": "..."}'
        }),
        ('Status', {
            'fields': ('is_active',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def get_title_preview(self, obj):
        title = obj.get_translated_value(obj.title, 'en')
        return title[:50] + '...' if len(title) > 50 else title
    get_title_preview.short_description = 'Title'
    
    def items_count(self, obj):
        return obj.items.count()
    items_count.short_description = 'Items'


@admin.register(FeatureItem)
class FeatureItemAdmin(admin.ModelAdmin):
    """Admin for Feature Items (standalone view)."""
    list_display = ['id', 'get_title_preview', 'section', 'order', 'is_active', 'created_at']
    list_filter = ['section', 'is_active', 'created_at']
    search_fields = ['title', 'description']
    list_editable = ['order', 'is_active']
    readonly_fields = ['created_at', 'updated_at', 'icon_preview']
    ordering = ['section', 'order']
    
    fieldsets = (
        ('Section', {
            'fields': ('section',),
        }),
        ('Icon', {
            'fields': ('icon', 'icon_image', 'icon_url', 'icon_preview'),
            'description': 'Use Lucide icon name OR upload an image OR provide URL'
        }),
        ('Content', {
            'fields': ('title', 'description'),
            'description': 'Enter translations as JSON: {"fr": "...", "ar": "...", "en": "..."}'
        }),
        ('Display', {
            'fields': ('order', 'is_active'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def get_title_preview(self, obj):
        title = obj.get_translated_value(obj.title, 'en')
        return title[:40] + '...' if len(title) > 40 else title
    get_title_preview.short_description = 'Title'
    
    def icon_preview(self, obj):
        icon_data = obj.get_icon_value()
        if icon_data['type'] in ['image', 'url']:
            return format_html('<img src="{}" style="max-height: 40px; max-width: 40px;" />', icon_data['value'])
        return f"Lucide: {icon_data['value']}"
    icon_preview.short_description = 'Icon Preview'


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    """Admin for Partners."""
    list_display = ['id', 'name', 'logo_preview', 'website_url', 'order', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'website_url']
    list_editable = ['order', 'is_active']
    readonly_fields = ['created_at', 'updated_at', 'logo_preview']
    ordering = ['order']
    
    fieldsets = (
        ('Partner Info', {
            'fields': ('name', 'website_url'),
        }),
        ('Logo', {
            'fields': ('logo', 'logo_url', 'logo_preview'),
        }),
        ('Display', {
            'fields': ('order', 'is_active'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def logo_preview(self, obj):
        url = obj.get_logo_url()
        if url:
            return format_html('<img src="{}" style="max-height: 50px; max-width: 100px;" />', url)
        return 'No logo'
    logo_preview.short_description = 'Preview'


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    """Admin for FAQ Items."""
    list_display = ['id', 'get_question_preview', 'order', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['question', 'answer']
    list_editable = ['order', 'is_active']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['order']
    
    fieldsets = (
        ('Content', {
            'fields': ('question', 'answer'),
            'description': 'Enter translations as JSON: {"fr": "...", "ar": "...", "en": "..."}'
        }),
        ('Display', {
            'fields': ('order', 'is_active'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def get_question_preview(self, obj):
        question = obj.get_translated_value(obj.question, 'en')
        return question[:60] + '...' if len(question) > 60 else question
    get_question_preview.short_description = 'Question'


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    """Admin for Testimonials."""
    list_display = ['id', 'author_name', 'rating', 'order', 'is_active', 'created_at']
    list_filter = ['rating', 'is_active', 'created_at']
    search_fields = ['author_name', 'content']
    list_editable = ['order', 'is_active']
    readonly_fields = ['created_at', 'updated_at', 'author_image_preview']
    ordering = ['order']
    
    fieldsets = (
        ('Author', {
            'fields': ('author_name', 'author_title', 'author_image', 'author_image_url', 'author_image_preview'),
        }),
        ('Content', {
            'fields': ('content', 'rating'),
            'description': 'Enter translations as JSON: {"fr": "...", "ar": "...", "en": "..."}'
        }),
        ('Display', {
            'fields': ('order', 'is_active'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def author_image_preview(self, obj):
        url = obj.get_author_image_url()
        if url:
            return format_html('<img src="{}" style="max-height: 50px; max-width: 50px; border-radius: 50%;" />', url)
        return 'No image'
    author_image_preview.short_description = 'Preview'
