"""
Landing Page CMS Models

Architecture Decision: JSON Translation Fields
----------------------------------------------
We use JSONField for translations instead of django-modeltranslation/django-parler because:
1. Single query fetches all translations - no JOINs needed
2. Schema simplicity - no table duplication or complex migrations  
3. Flexible - add new languages without migrations
4. Frontend-friendly - JSON maps directly to React/Next.js needs
5. PostgreSQL JSONB provides excellent query performance

Translation JSON structure:
{
    "fr": "Texte français",
    "ar": "النص العربي",
    "en": "English text"
}
"""

from django.db import models
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
import json


# =============================================================================
# CONSTANTS
# =============================================================================

SUPPORTED_LANGUAGES = ['fr', 'ar', 'en']
DEFAULT_LANGUAGE = 'fr'
FALLBACK_ORDER = ['fr', 'en', 'ar']


# =============================================================================
# VALIDATORS
# =============================================================================

def validate_translation_json(value):
    """
    Validates that the JSON contains at least one supported language.
    Ensures proper encoding for Arabic (RTL) content.
    """
    if not isinstance(value, dict):
        raise ValidationError("Translation must be a JSON object/dictionary.")
    
    # Check if at least one supported language is present
    has_valid_lang = any(lang in value for lang in SUPPORTED_LANGUAGES)
    if not has_valid_lang:
        raise ValidationError(
            f"Translation must contain at least one of: {', '.join(SUPPORTED_LANGUAGES)}"
        )
    
    # Validate that values are strings
    for lang, text in value.items():
        if lang in SUPPORTED_LANGUAGES and text is not None:
            if not isinstance(text, str):
                raise ValidationError(f"Translation for '{lang}' must be a string.")
    
    return value


# =============================================================================
# ABSTRACT BASE MODELS
# =============================================================================

class TimeStampedModel(models.Model):
    """Abstract base model with created/updated timestamps."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True


class OrderedModel(models.Model):
    """Abstract base model for orderable items."""
    order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        abstract = True
        ordering = ['order']


class TranslatableFieldMixin:
    """
    Mixin providing helper methods for translatable JSON fields.
    """
    
    @staticmethod
    def get_translated_value(translations: dict, lang: str = DEFAULT_LANGUAGE) -> str:
        """
        Get translation with fallback logic.
        Fallback order: requested lang → fr → en → ar → first available → empty string
        """
        if not translations or not isinstance(translations, dict):
            return ""
        
        # Try requested language first
        if lang in translations and translations[lang]:
            return translations[lang]
        
        # Fallback through preferred order
        for fallback_lang in FALLBACK_ORDER:
            if fallback_lang in translations and translations[fallback_lang]:
                return translations[fallback_lang]
        
        # Last resort: return first non-empty value
        for value in translations.values():
            if value:
                return value
        
        return ""


# =============================================================================
# HERO SECTION
# =============================================================================

class HeroSection(TimeStampedModel, TranslatableFieldMixin):
    """
    Hero section of the landing page.
    Only one active hero section should exist at a time.
    """
    title = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    subtitle = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    description = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    background_image = models.ImageField(
        upload_to='hero/',
        null=True,
        blank=True
    )
    background_image_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="External URL for background image (used if no file uploaded)"
    )
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        verbose_name = "Hero Section"
        verbose_name_plural = "Hero Sections"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Hero: {self.get_translated_value(self.title, 'en')[:50]}"
    
    def get_background_url(self):
        """Returns the background image URL (file takes precedence over URL)."""
        if self.background_image:
            return self.background_image.url
        return self.background_image_url
    
    @classmethod
    def get_active(cls):
        """Get the currently active hero section."""
        return cls.objects.filter(is_active=True).first()


# =============================================================================
# FEATURES SECTION
# =============================================================================

class FeaturesSection(TimeStampedModel, TranslatableFieldMixin):
    """
    Features section header/container.
    Contains the section title/subtitle and related FeatureItem entries.
    """
    title = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    subtitle = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        verbose_name = "Features Section"
        verbose_name_plural = "Features Sections"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Features: {self.get_translated_value(self.title, 'en')[:50]}"
    
    @classmethod
    def get_active(cls):
        """Get the currently active features section with prefetched items."""
        return cls.objects.filter(is_active=True).prefetch_related(
            models.Prefetch(
                'items',
                queryset=FeatureItem.objects.filter(is_active=True).order_by('order')
            )
        ).first()


class FeatureItem(TimeStampedModel, OrderedModel, TranslatableFieldMixin):
    """
    Individual feature item within the Features section.
    """
    section = models.ForeignKey(
        FeaturesSection,
        on_delete=models.CASCADE,
        related_name='items'
    )
    icon = models.CharField(
        max_length=100,
        blank=True,
        help_text="Lucide icon name (e.g., 'rocket', 'shield', 'zap')"
    )
    icon_image = models.ImageField(
        upload_to='features/icons/',
        null=True,
        blank=True,
        help_text="Custom icon image (takes precedence over icon name)"
    )
    icon_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="External URL for icon image"
    )
    title = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    description = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    
    class Meta:
        verbose_name = "Feature Item"
        verbose_name_plural = "Feature Items"
        ordering = ['order']
    
    def __str__(self):
        return f"Feature: {self.get_translated_value(self.title, 'en')[:50]}"
    
    def get_icon_value(self):
        """
        Returns icon info with type indicator.
        Priority: icon_image > icon_url > icon (lucide name)
        """
        if self.icon_image:
            return {'type': 'image', 'value': self.icon_image.url}
        elif self.icon_url:
            return {'type': 'url', 'value': self.icon_url}
        elif self.icon:
            return {'type': 'lucide', 'value': self.icon}
        return {'type': 'lucide', 'value': 'star'}  # Default icon


# =============================================================================
# PARTNERS SECTION
# =============================================================================

class Partner(TimeStampedModel, OrderedModel):
    """
    Partner/sponsor entry for the Partners section.
    Name is not translated as it's a proper noun/brand name.
    """
    name = models.CharField(max_length=200)
    logo = models.ImageField(
        upload_to='partners/',
        null=True,
        blank=True
    )
    logo_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="External URL for logo (used if no file uploaded)"
    )
    website_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Partner's website URL"
    )
    
    class Meta:
        verbose_name = "Partner"
        verbose_name_plural = "Partners"
        ordering = ['order']
    
    def __str__(self):
        return self.name
    
    def get_logo_url(self):
        """Returns the logo URL (file takes precedence over URL)."""
        if self.logo:
            return self.logo.url
        return self.logo_url
    
    @classmethod
    def get_active_partners(cls):
        """Get all active partners ordered by order field."""
        return cls.objects.filter(is_active=True).order_by('order')


# =============================================================================
# FAQ SECTION
# =============================================================================

class FAQItem(TimeStampedModel, OrderedModel, TranslatableFieldMixin):
    """
    FAQ entry with translatable question and answer.
    """
    question = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    answer = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."} - Supports long text/HTML'
    )
    
    class Meta:
        verbose_name = "FAQ Item"
        verbose_name_plural = "FAQ Items"
        ordering = ['order']
    
    def __str__(self):
        return f"FAQ: {self.get_translated_value(self.question, 'en')[:50]}"
    
    @classmethod
    def get_active_faqs(cls):
        """Get all active FAQ items ordered by order field."""
        return cls.objects.filter(is_active=True).order_by('order')


# =============================================================================
# TESTIMONIALS SECTION (Bonus - common for landing pages)
# =============================================================================

class Testimonial(TimeStampedModel, OrderedModel, TranslatableFieldMixin):
    """
    Testimonial/review entry.
    """
    author_name = models.CharField(max_length=200)
    author_title = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"fr": "...", "ar": "...", "en": "..."} - Author role/position'
    )
    author_image = models.ImageField(
        upload_to='testimonials/',
        null=True,
        blank=True
    )
    author_image_url = models.URLField(
        max_length=500,
        null=True,
        blank=True
    )
    content = models.JSONField(
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "ar": "...", "en": "..."}'
    )
    rating = models.PositiveSmallIntegerField(
        default=5,
        help_text="Rating out of 5"
    )
    
    class Meta:
        verbose_name = "Testimonial"
        verbose_name_plural = "Testimonials"
        ordering = ['order']
    
    def __str__(self):
        return f"Testimonial by {self.author_name}"
    
    def get_author_image_url(self):
        """Returns the author image URL."""
        if self.author_image:
            return self.author_image.url
        return self.author_image_url
    
    @classmethod
    def get_active_testimonials(cls):
        """Get all active testimonials ordered by order field."""
        return cls.objects.filter(is_active=True).order_by('order')
