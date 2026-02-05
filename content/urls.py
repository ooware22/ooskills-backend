"""
Landing Page CMS URL Configuration

Public endpoints (read-only):
    /api/public/landing/             - Aggregated landing page data
    /api/public/landing/hero/        - Hero section only
    /api/public/landing/features/    - Features section with items
    /api/public/landing/partners/    - Partners list
    /api/public/landing/faq/         - FAQ items list
    /api/public/landing/testimonials/ - Testimonials list
    /api/public/settings/            - Site settings (SEO meta, toggles, etc.)

Admin endpoints (CRUD):
    /api/admin/cms/hero/             - Hero CRUD
    /api/admin/cms/features/         - Features sections CRUD
    /api/admin/cms/feature-items/    - Feature items CRUD
    /api/admin/cms/partners/         - Partners CRUD
    /api/admin/cms/faq/              - FAQ CRUD
    /api/admin/cms/testimonials/     - Testimonials CRUD
    /api/admin/cms/settings/         - Site settings CRUD
    /api/admin/cms/invalidate-cache/ - Cache invalidation
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    # Public views
    PublicLandingPageView,
    PublicHeroView,
    PublicFeaturesView,
    PublicPartnersView,
    PublicFAQView,
    PublicTestimonialsView,
    PublicSiteSettingsView,
    # Admin viewsets
    AdminHeroViewSet,
    AdminFeaturesSectionViewSet,
    AdminFeatureItemViewSet,
    AdminPartnerViewSet,
    AdminFAQSectionViewSet,
    AdminFAQItemViewSet,
    AdminTestimonialViewSet,
    AdminSiteSettingsViewSet,
    InvalidateCacheView,
)


# =============================================================================
# ADMIN ROUTER
# =============================================================================

admin_router = DefaultRouter()
admin_router.register(r'hero', AdminHeroViewSet, basename='admin-hero')
admin_router.register(r'features', AdminFeaturesSectionViewSet, basename='admin-features')
admin_router.register(r'feature-items', AdminFeatureItemViewSet, basename='admin-feature-items')
admin_router.register(r'partners', AdminPartnerViewSet, basename='admin-partners')
admin_router.register(r'faq', AdminFAQSectionViewSet, basename='admin-faq')
admin_router.register(r'faq-items', AdminFAQItemViewSet, basename='admin-faq-items')
admin_router.register(r'testimonials', AdminTestimonialViewSet, basename='admin-testimonials')
admin_router.register(r'settings', AdminSiteSettingsViewSet, basename='admin-settings')


# =============================================================================
# URL PATTERNS
# =============================================================================

# Public URL patterns (prefix: /api/public/landing/)
public_urlpatterns = [
    path('', PublicLandingPageView.as_view(), name='public-landing'),
    path('hero/', PublicHeroView.as_view(), name='public-hero'),
    path('features/', PublicFeaturesView.as_view(), name='public-features'),
    path('partners/', PublicPartnersView.as_view(), name='public-partners'),
    path('faq/', PublicFAQView.as_view(), name='public-faq'),
    path('testimonials/', PublicTestimonialsView.as_view(), name='public-testimonials'),
]

# Site settings public URL (separate from landing to allow independent caching)
settings_urlpatterns = [
    path('', PublicSiteSettingsView.as_view(), name='public-settings'),
]

# Admin URL patterns (prefix: /api/admin/cms/)
admin_urlpatterns = [
    path('', include(admin_router.urls)),
    path('invalidate-cache/', InvalidateCacheView.as_view(), name='invalidate-cache'),
]



# Combined app URLs
app_name = 'content'

urlpatterns = [
    path('public/landing/', include((public_urlpatterns, 'public'))),
    path('public/settings/', include((settings_urlpatterns, 'settings'))),
    path('admin/cms/', include((admin_urlpatterns, 'admin'))),
]
