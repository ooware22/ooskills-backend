"""
Landing Page CMS Views

Public endpoints (read-only):
- GET /api/public/landing/?lang=fr - Aggregated landing page data
- GET /api/public/landing/hero/?lang=fr
- GET /api/public/landing/features/?lang=fr
- GET /api/public/landing/partners/
- GET /api/public/landing/faq/?lang=fr
- GET /api/public/landing/testimonials/?lang=fr

Admin endpoints (CRUD):
- /api/admin/cms/hero/
- /api/admin/cms/features/
- /api/admin/cms/feature-items/
- /api/admin/cms/partners/
- /api/admin/cms/faq/
- /api/admin/cms/testimonials/
"""

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db.models import Prefetch

from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny

from .models import (
    HeroSection, FeaturesSection, FeatureItem,
    Partner, FAQSection, FAQItem, Testimonial, SiteSettings,
    SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
)
from .serializers import (
    # Public serializers
    PublicHeroSerializer, PublicFeaturesSectionSerializer,
    PublicPartnerSerializer, PublicFAQItemSerializer, PublicFAQSectionSerializer,
    PublicTestimonialSerializer, PublicLandingPageSerializer,
    PublicSiteSettingsSerializer,
    # Admin serializers
    AdminHeroSerializer, AdminFeaturesSectionSerializer,
    AdminFeatureItemSerializer, AdminPartnerSerializer,
    AdminFAQSectionSerializer, AdminFAQItemSerializer, AdminTestimonialSerializer,
    AdminSiteSettingsSerializer,
    BulkOrderUpdateSerializer
)
from .permissions import IsAdminOrSuperAdmin, IsAdminOrReadOnly, PublicReadOnly


# =============================================================================
# LANGUAGE MIXIN
# =============================================================================

class LanguageMixin:
    """Mixin to handle language parameter validation and context."""
    
    def get_language(self):
        """Get and validate language from query params."""
        lang = self.request.query_params.get('lang', DEFAULT_LANGUAGE)
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        return lang
    
    def get_serializer_context(self):
        """Add language to serializer context."""
        context = super().get_serializer_context()
        context['lang'] = self.get_language()
        return context


# =============================================================================
# PUBLIC VIEWS (Read-only, cached)
# =============================================================================

class PublicLandingPageView(LanguageMixin, APIView):
    """
    GET /api/public/landing/?lang=fr
    
    Returns aggregated landing page data in a single response.
    Optimized for homepage load - single API call.
    Cached for 5 minutes to reduce database load.
    """
    permission_classes = [AllowAny]
    
    @method_decorator(cache_page(60 * 5))  # Cache for 5 minutes
    def get(self, request, *args, **kwargs):
        lang = self.get_language()
        context = {'lang': lang, 'request': request}
        
        # Fetch all data with optimized queries
        hero = HeroSection.objects.filter(is_active=True).first()
        
        features = FeaturesSection.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'items',
                queryset=FeatureItem.objects.filter(is_active=True).order_by('order')
            )
        ).first()
        
        partners = Partner.objects.filter(is_active=True).order_by('order')
        
        # Fetch FAQ section with items
        faq_section = FAQSection.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'items',
                queryset=FAQItem.objects.filter(is_active=True).order_by('order')
            )
        ).first()
        
        testimonials = Testimonial.objects.filter(is_active=True).order_by('order')
        
        # Get site settings
        settings = SiteSettings.get_settings()
        settings_data = PublicSiteSettingsSerializer(settings, context=context).data
        
        # Serialize
        data = {
            'hero': PublicHeroSerializer(hero, context=context).data if hero else None,
            'features': PublicFeaturesSectionSerializer(features, context=context).data if features else None,
            'partners': PublicPartnerSerializer(partners, many=True, context=context).data,
            'faq': PublicFAQSectionSerializer(faq_section, context=context).data if faq_section else None,
            'testimonials': PublicTestimonialSerializer(testimonials, many=True, context=context).data,
            'settings': settings_data,
            'meta': {
                'lang': lang,
                'supported_languages': SUPPORTED_LANGUAGES,
                'default_language': settings.default_language or DEFAULT_LANGUAGE,
            }
        }
        
        return Response(data)
    
    def get_language(self):
        """Get and validate language from query params."""
        lang = self.request.query_params.get('lang', DEFAULT_LANGUAGE)
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        return lang


class PublicHeroView(LanguageMixin, generics.RetrieveAPIView):
    """
    GET /api/public/landing/hero/?lang=fr
    
    Returns the active hero section.
    """
    permission_classes = [AllowAny]
    serializer_class = PublicHeroSerializer
    
    @method_decorator(cache_page(60 * 5))
    def get(self, request, *args, **kwargs):
        hero = HeroSection.objects.filter(is_active=True).first()
        if not hero:
            return Response(
                {'detail': 'No active hero section found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(hero)
        return Response(serializer.data)


class PublicFeaturesView(LanguageMixin, generics.RetrieveAPIView):
    """
    GET /api/public/landing/features/?lang=fr
    
    Returns the active features section with items.
    """
    permission_classes = [AllowAny]
    serializer_class = PublicFeaturesSectionSerializer
    
    @method_decorator(cache_page(60 * 5))
    def get(self, request, *args, **kwargs):
        features = FeaturesSection.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'items',
                queryset=FeatureItem.objects.filter(is_active=True).order_by('order')
            )
        ).first()
        
        if not features:
            return Response(
                {'detail': 'No active features section found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(features)
        return Response(serializer.data)


class PublicPartnersView(LanguageMixin, generics.ListAPIView):
    """
    GET /api/public/landing/partners/
    
    Returns all active partners (no translation needed).
    """
    permission_classes = [AllowAny]
    serializer_class = PublicPartnerSerializer
    
    @method_decorator(cache_page(60 * 5))
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
    
    def get_queryset(self):
        return Partner.objects.filter(is_active=True).order_by('order')


class PublicFAQView(LanguageMixin, generics.RetrieveAPIView):
    """
    GET /api/public/landing/faq/?lang=fr
    
    Returns the active FAQ section with title, subtitle, and nested items.
    """
    permission_classes = [AllowAny]
    serializer_class = PublicFAQSectionSerializer
    
    @method_decorator(cache_page(60 * 5))
    def get(self, request, *args, **kwargs):
        faq_section = FAQSection.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'items',
                queryset=FAQItem.objects.filter(is_active=True).order_by('order')
            )
        ).first()
        
        if not faq_section:
            return Response(
                {'detail': 'No active FAQ section found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(faq_section)
        return Response(serializer.data)


class PublicTestimonialsView(LanguageMixin, generics.ListAPIView):
    """
    GET /api/public/landing/testimonials/?lang=fr
    
    Returns all active testimonials.
    """
    permission_classes = [AllowAny]
    serializer_class = PublicTestimonialSerializer
    
    @method_decorator(cache_page(60 * 5))
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
    
    def get_queryset(self):
        return Testimonial.objects.filter(is_active=True).order_by('order')


# =============================================================================
# ADMIN VIEWSETS (Full CRUD)
# =============================================================================

class AdminHeroViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for Hero sections.
    
    GET /api/admin/cms/hero/ - List all
    POST /api/admin/cms/hero/ - Create new
    GET /api/admin/cms/hero/{id}/ - Retrieve
    PUT /api/admin/cms/hero/{id}/ - Update
    PATCH /api/admin/cms/hero/{id}/ - Partial update
    DELETE /api/admin/cms/hero/{id}/ - Delete
    """
    queryset = HeroSection.objects.all().order_by('-created_at')
    serializer_class = AdminHeroSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get the currently active hero section."""
        hero = HeroSection.objects.filter(is_active=True).first()
        if not hero:
            return Response({'detail': 'No active hero section.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(hero)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Set this hero as active and deactivate others."""
        hero = self.get_object()
        # Deactivate all others
        HeroSection.objects.exclude(pk=hero.pk).update(is_active=False)
        hero.is_active = True
        hero.save()
        serializer = self.get_serializer(hero)
        return Response(serializer.data)


class AdminFeaturesSectionViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for Features sections.
    """
    queryset = FeaturesSection.objects.all().prefetch_related('items').order_by('-created_at')
    serializer_class = AdminFeaturesSectionSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get the currently active features section."""
        section = FeaturesSection.objects.filter(is_active=True).prefetch_related('items').first()
        if not section:
            return Response({'detail': 'No active features section.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(section)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Set this features section as active and deactivate others."""
        section = self.get_object()
        FeaturesSection.objects.exclude(pk=section.pk).update(is_active=False)
        section.is_active = True
        section.save()
        serializer = self.get_serializer(section)
        return Response(serializer.data)


class AdminFeatureItemViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for Feature items.
    
    Supports filtering by section:
    GET /api/admin/cms/feature-items/?section=1
    """
    queryset = FeatureItem.objects.all().select_related('section').order_by('order')
    serializer_class = AdminFeatureItemSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        section_id = self.request.query_params.get('section')
        if section_id:
            queryset = queryset.filter(section_id=section_id)
        return queryset
    
    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """
        Bulk reorder feature items.
        POST /api/admin/cms/feature-items/reorder/
        Body: {"items": [{"id": 1, "order": 0}, {"id": 2, "order": 1}]}
        """
        serializer = BulkOrderUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        items_data = serializer.validated_data['items']
        for item_data in items_data:
            FeatureItem.objects.filter(pk=item_data['id']).update(order=item_data['order'])
        
        return Response({'status': 'reordered', 'count': len(items_data)})


class AdminPartnerViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for Partners.
    """
    queryset = Partner.objects.all().order_by('order')
    serializer_class = AdminPartnerSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Bulk reorder partners."""
        serializer = BulkOrderUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        items_data = serializer.validated_data['items']
        for item_data in items_data:
            Partner.objects.filter(pk=item_data['id']).update(order=item_data['order'])
        
        return Response({'status': 'reordered', 'count': len(items_data)})


class AdminFAQSectionViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for FAQ sections (title/subtitle).
    
    GET /api/admin/cms/faq/ - List all sections
    POST /api/admin/cms/faq/ - Create new section
    GET /api/admin/cms/faq/{id}/ - Retrieve
    PUT /api/admin/cms/faq/{id}/ - Update
    DELETE /api/admin/cms/faq/{id}/ - Delete
    """
    queryset = FAQSection.objects.all().order_by('-created_at')
    serializer_class = AdminFAQSectionSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    def get_queryset(self):
        return FAQSection.objects.prefetch_related('items').order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Set this FAQ section as active and deactivate others."""
        faq_section = self.get_object()
        FAQSection.objects.exclude(pk=faq_section.pk).update(is_active=False)
        faq_section.is_active = True
        faq_section.save()
        return Response({'status': 'activated', 'id': faq_section.id})
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get the currently active FAQ section."""
        faq_section = FAQSection.objects.filter(is_active=True).prefetch_related('items').first()
        if faq_section:
            serializer = self.get_serializer(faq_section)
            return Response(serializer.data)
        return Response({'detail': 'No active FAQ section'}, status=status.HTTP_404_NOT_FOUND)


class AdminFAQItemViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for FAQ items.
    
    GET /api/admin/cms/faq-items/ - List all items
    POST /api/admin/cms/faq-items/ - Create new item
    GET /api/admin/cms/faq-items/{id}/ - Retrieve
    PUT /api/admin/cms/faq-items/{id}/ - Update
    DELETE /api/admin/cms/faq-items/{id}/ - Delete
    """
    queryset = FAQItem.objects.all().order_by('order')
    serializer_class = AdminFAQItemSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Bulk reorder FAQ items."""
        serializer = BulkOrderUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        items_data = serializer.validated_data['items']
        for item_data in items_data:
            FAQItem.objects.filter(pk=item_data['id']).update(order=item_data['order'])
        
        return Response({'status': 'reordered', 'count': len(items_data)})


class AdminTestimonialViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for Testimonials.
    """
    queryset = Testimonial.objects.all().order_by('order')
    serializer_class = AdminTestimonialSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Bulk reorder testimonials."""
        serializer = BulkOrderUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        items_data = serializer.validated_data['items']
        for item_data in items_data:
            Testimonial.objects.filter(pk=item_data['id']).update(order=item_data['order'])
        
        return Response({'status': 'reordered', 'count': len(items_data)})


# =============================================================================
# CACHE INVALIDATION VIEW
# =============================================================================

class InvalidateCacheView(APIView):
    """
    POST /api/admin/cms/invalidate-cache/
    
    Manually invalidate the landing page cache.
    Call this after content updates if immediate refresh is needed.
    """
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    def post(self, request):
        from django.core.cache import cache
        
        # Clear all cache (simple approach)
        # For more granular control, use cache keys prefixes
        cache.clear()
        
        return Response({
            'status': 'success',
            'message': 'Cache invalidated. New requests will fetch fresh data.'
        })


# =============================================================================
# SITE SETTINGS VIEWS
# =============================================================================

class PublicSiteSettingsView(LanguageMixin, APIView):
    """
    GET /api/public/settings/?lang=fr
    
    Returns site settings including SEO meta, feature toggles, etc.
    Cached for 5 minutes.
    """
    permission_classes = [AllowAny]
    
    @method_decorator(cache_page(60 * 5))
    def get(self, request, *args, **kwargs):
        lang = self.get_language()
        context = {'lang': lang, 'request': request}
        
        settings = SiteSettings.get_settings()
        serializer = PublicSiteSettingsSerializer(settings, context=context)
        return Response(serializer.data)


class AdminSiteSettingsViewSet(viewsets.ViewSet):
    """
    GET /api/admin/cms/settings/
    PUT /api/admin/cms/settings/
    PATCH /api/admin/cms/settings/
    
    Get or update site settings (singleton - only one instance).
    """
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
    
    def list(self, request):
        """GET /api/admin/cms/settings/ - Get site settings."""
        settings = SiteSettings.get_settings()
        serializer = AdminSiteSettingsSerializer(settings)
        return Response(serializer.data)
    
    def retrieve(self, request, pk=None):
        """GET /api/admin/cms/settings/{pk}/ - Get site settings (redirect to list)."""
        return self.list(request)
    
    @action(detail=False, methods=['put', 'patch'])
    def update_settings(self, request):
        """PUT/PATCH /api/admin/cms/settings/update_settings/ - Update site settings."""
        partial = request.method == 'PATCH'
        settings = SiteSettings.get_settings()
        serializer = AdminSiteSettingsSerializer(settings, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
