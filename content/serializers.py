"""
Landing Page CMS Serializers

Provides serializers for both public (read-only, language-specific) 
and admin (CRUD, full translation access) endpoints.
"""

from rest_framework import serializers
from .models import (
    HeroSection, FeaturesSection, FeatureItem,
    Partner, FAQItem, Testimonial,
    SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, FALLBACK_ORDER
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

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
# TRANSLATION FIELD SERIALIZERS
# =============================================================================

class TranslationField(serializers.JSONField):
    """
    Custom field for translation JSON.
    Validates structure and ensures proper encoding.
    """
    def to_internal_value(self, data):
        if isinstance(data, str):
            import json
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                raise serializers.ValidationError("Invalid JSON string")
        
        if not isinstance(data, dict):
            raise serializers.ValidationError("Translation must be a JSON object")
        
        # Validate at least one supported language
        has_valid = any(lang in data for lang in SUPPORTED_LANGUAGES)
        if not has_valid:
            raise serializers.ValidationError(
                f"Must contain at least one of: {', '.join(SUPPORTED_LANGUAGES)}"
            )
        
        return super().to_internal_value(data)


# =============================================================================
# PUBLIC SERIALIZERS (Read-only, language-specific output)
# =============================================================================

class PublicHeroSerializer(serializers.ModelSerializer):
    """Public Hero section - returns translated strings for requested language."""
    title = serializers.SerializerMethodField()
    subtitle = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    background_image = serializers.SerializerMethodField()
    
    class Meta:
        model = HeroSection
        fields = ['id', 'title', 'subtitle', 'description', 'background_image']
    
    def get_title(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.title, lang)
    
    def get_subtitle(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.subtitle, lang)
    
    def get_description(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.description, lang)
    
    def get_background_image(self, obj):
        return obj.get_background_url()


class PublicFeatureItemSerializer(serializers.ModelSerializer):
    """Public Feature item - returns translated strings."""
    title = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    icon = serializers.SerializerMethodField()
    
    class Meta:
        model = FeatureItem
        fields = ['id', 'icon', 'title', 'description', 'order']
    
    def get_title(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.title, lang)
    
    def get_description(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.description, lang)
    
    def get_icon(self, obj):
        return obj.get_icon_value()


class PublicFeaturesSectionSerializer(serializers.ModelSerializer):
    """Public Features section with items."""
    title = serializers.SerializerMethodField()
    subtitle = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    
    class Meta:
        model = FeaturesSection
        fields = ['id', 'title', 'subtitle', 'items']
    
    def get_title(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.title, lang)
    
    def get_subtitle(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.subtitle, lang)
    
    def get_items(self, obj):
        # Use prefetched items if available, otherwise filter
        items = getattr(obj, '_prefetched_objects_cache', {}).get('items')
        if items is None:
            items = obj.items.filter(is_active=True).order_by('order')
        return PublicFeatureItemSerializer(items, many=True, context=self.context).data


class PublicPartnerSerializer(serializers.ModelSerializer):
    """Public Partner - no translation needed."""
    logo = serializers.SerializerMethodField()
    
    class Meta:
        model = Partner
        fields = ['id', 'name', 'logo', 'website_url', 'order']
    
    def get_logo(self, obj):
        return obj.get_logo_url()


class PublicFAQItemSerializer(serializers.ModelSerializer):
    """Public FAQ item - returns translated strings."""
    question = serializers.SerializerMethodField()
    answer = serializers.SerializerMethodField()
    
    class Meta:
        model = FAQItem
        fields = ['id', 'question', 'answer', 'order']
    
    def get_question(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.question, lang)
    
    def get_answer(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.answer, lang)


class PublicTestimonialSerializer(serializers.ModelSerializer):
    """Public Testimonial - returns translated strings."""
    author_title = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    author_image = serializers.SerializerMethodField()
    
    class Meta:
        model = Testimonial
        fields = ['id', 'author_name', 'author_title', 'author_image', 'content', 'rating', 'order']
    
    def get_author_title(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.author_title, lang)
    
    def get_content(self, obj):
        lang = self.context.get('lang', DEFAULT_LANGUAGE)
        return get_translated_value(obj.content, lang)
    
    def get_author_image(self, obj):
        return obj.get_author_image_url()


class PublicLandingPageSerializer(serializers.Serializer):
    """
    Aggregated landing page data - single API call for entire homepage.
    Optimized to minimize frontend requests.
    """
    hero = PublicHeroSerializer(read_only=True)
    features = PublicFeaturesSectionSerializer(read_only=True)
    partners = PublicPartnerSerializer(many=True, read_only=True)
    faq = PublicFAQItemSerializer(many=True, read_only=True)
    testimonials = PublicTestimonialSerializer(many=True, read_only=True)
    meta = serializers.SerializerMethodField()
    
    def get_meta(self, obj):
        return {
            'lang': self.context.get('lang', DEFAULT_LANGUAGE),
            'supported_languages': SUPPORTED_LANGUAGES,
            'default_language': DEFAULT_LANGUAGE
        }


# =============================================================================
# ADMIN SERIALIZERS (Full CRUD with all translations)
# =============================================================================

class AdminHeroSerializer(serializers.ModelSerializer):
    """Admin Hero section - full translation access."""
    title = TranslationField()
    subtitle = TranslationField()
    description = TranslationField()
    background_image_display = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = HeroSection
        fields = [
            'id', 'title', 'subtitle', 'description',
            'background_image', 'background_image_url', 'background_image_display',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'background_image_display']
    
    def get_background_image_display(self, obj):
        return obj.get_background_url()


class AdminFeatureItemSerializer(serializers.ModelSerializer):
    """Admin Feature item - full translation access."""
    title = TranslationField()
    description = TranslationField()
    icon_display = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = FeatureItem
        fields = [
            'id', 'section', 'icon', 'icon_image', 'icon_url', 'icon_display',
            'title', 'description', 'order', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'icon_display']
    
    def get_icon_display(self, obj):
        return obj.get_icon_value()


class AdminFeaturesSectionSerializer(serializers.ModelSerializer):
    """Admin Features section - full translation access."""
    title = TranslationField()
    subtitle = TranslationField()
    items = AdminFeatureItemSerializer(many=True, read_only=True)
    items_count = serializers.SerializerMethodField()
    
    class Meta:
        model = FeaturesSection
        fields = [
            'id', 'title', 'subtitle', 'is_active',
            'items', 'items_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'items', 'items_count', 'created_at', 'updated_at']
    
    def get_items_count(self, obj):
        return obj.items.count()


class AdminPartnerSerializer(serializers.ModelSerializer):
    """Admin Partner - full access."""
    logo_display = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Partner
        fields = [
            'id', 'name', 'logo', 'logo_url', 'logo_display',
            'website_url', 'order', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'logo_display']
    
    def get_logo_display(self, obj):
        return obj.get_logo_url()


class AdminFAQItemSerializer(serializers.ModelSerializer):
    """Admin FAQ item - full translation access."""
    question = TranslationField()
    answer = TranslationField()
    
    class Meta:
        model = FAQItem
        fields = [
            'id', 'question', 'answer', 'order', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AdminTestimonialSerializer(serializers.ModelSerializer):
    """Admin Testimonial - full translation access."""
    author_title = TranslationField(required=False, allow_null=True)
    content = TranslationField()
    author_image_display = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Testimonial
        fields = [
            'id', 'author_name', 'author_title',
            'author_image', 'author_image_url', 'author_image_display',
            'content', 'rating', 'order', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'author_image_display']
    
    def get_author_image_display(self, obj):
        return obj.get_author_image_url()


# =============================================================================
# BULK UPDATE SERIALIZERS
# =============================================================================

class BulkOrderUpdateSerializer(serializers.Serializer):
    """For bulk reordering of items."""
    items = serializers.ListField(
        child=serializers.DictField(
            child=serializers.IntegerField()
        ),
        help_text='[{"id": 1, "order": 0}, {"id": 2, "order": 1}, ...]'
    )
    
    def validate_items(self, value):
        for item in value:
            if 'id' not in item or 'order' not in item:
                raise serializers.ValidationError(
                    "Each item must have 'id' and 'order' fields"
                )
        return value
