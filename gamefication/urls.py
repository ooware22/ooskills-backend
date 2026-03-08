"""
Gamification URL configuration.

All endpoints are prefixed with /api/gamification/ (set in root urls.py).
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from gamefication import views

router = DefaultRouter()
router.register(r'profile', views.UserXPViewSet, basename='gamification-profile')
router.register(r'xp-history', views.XPTransactionViewSet, basename='xp-history')
router.register(r'achievements', views.AchievementViewSet, basename='achievement')
router.register(r'leaderboard', views.LeaderboardViewSet, basename='leaderboard')
router.register(r'admin-achievements', views.AdminAchievementViewSet, basename='admin-achievement')

urlpatterns = [
    path('', include(router.urls)),
]
