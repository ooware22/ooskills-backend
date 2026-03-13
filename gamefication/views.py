"""
Gamification Views — DRF ViewSets for XP profile, history, achievements, leaderboard.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from gamefication.models import (
    AchievementDefinition,
    LeaderboardCache,
    LeaderboardPeriod,
    UserXP,
    XPTransaction,
)
from gamefication.serializers import (
    AchievementSerializer,
    AdminAchievementSerializer,
    LeaderboardEntrySerializer,
    UserXPSerializer,
    XPTransactionSerializer,
)
from gamefication.services.xp_service import get_or_create_xp_profile
from gamefication.services.leaderboard_service import refresh_leaderboard


# ─── User XP Profile ────────────────────────────────────────────────────────

class UserXPViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    GET /api/gamification/profile/
    POST /api/gamification/profile/toggle-visibility/

    Returns the current user's XP profile (level, XP, streak, progress).
    Uses list() to return a single object (no pk needed).
    """
    serializer_class = UserXPSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        user_xp = get_or_create_xp_profile(request.user)
        serializer = self.get_serializer(user_xp)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='toggle-visibility')
    def toggle_visibility(self, request):
        """Toggle the user's leaderboard visibility."""
        user_xp = get_or_create_xp_profile(request.user)
        user_xp.visible_on_leaderboard = not user_xp.visible_on_leaderboard
        user_xp.save(update_fields=['visible_on_leaderboard'])
        # Full refresh so the user appears/disappears immediately
        for period in [LeaderboardPeriod.ALLTIME, LeaderboardPeriod.WEEKLY]:
            refresh_leaderboard(period)
        return Response({
            'visible_on_leaderboard': user_xp.visible_on_leaderboard,
        })


# ─── XP Transaction History ─────────────────────────────────────────────────

class XPTransactionViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    GET /api/gamification/xp-history/

    Returns the current user's paginated XP transaction log.
    """
    serializer_class = XPTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return XPTransaction.objects.filter(user=self.request.user)


# ─── Achievements ────────────────────────────────────────────────────────────

class AchievementViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    GET /api/gamification/achievements/

    Returns all active achievement definitions with the current user's
    unlock status (unlocked: bool, unlocked_at: datetime).
    """
    serializer_class = AchievementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return AchievementDefinition.objects.filter(is_active=True)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        return context  # request is already in context by default


# ─── Leaderboard ─────────────────────────────────────────────────────────────

class LeaderboardViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """
    GET /api/gamification/leaderboard/?period=weekly|alltime

    Returns cached leaderboard rankings. If the cache is empty or stale,
    it auto-refreshes.
    """
    serializer_class = LeaderboardEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        period = self.request.query_params.get('period', LeaderboardPeriod.ALLTIME)
        if period not in [LeaderboardPeriod.WEEKLY, LeaderboardPeriod.ALLTIME]:
            period = LeaderboardPeriod.ALLTIME

        qs = LeaderboardCache.objects.filter(period=period).select_related('user')

        # Auto-refresh if cache is empty or stale (older than 5 minutes)
        needs_refresh = False
        if not qs.exists():
            needs_refresh = True
        else:
            latest = qs.order_by('-refreshed_at').values_list('refreshed_at', flat=True).first()
            if latest and (timezone.now() - latest) > timedelta(minutes=5):
                needs_refresh = True

        if needs_refresh:
            refresh_leaderboard(period)
            qs = LeaderboardCache.objects.filter(period=period).select_related('user')

        return qs


# ─── Admin Achievement CRUD ─────────────────────────────────────────────────

class AdminAchievementViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for achievement definitions.
    Admin-only: list, create, update, delete.
    GET /api/gamification/admin-achievements/
    POST /api/gamification/admin-achievements/
    PUT/PATCH /api/gamification/admin-achievements/<id>/
    DELETE /api/gamification/admin-achievements/<id>/
    """
    serializer_class = AdminAchievementSerializer
    permission_classes = [IsAuthenticated]
    queryset = AchievementDefinition.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search', '')
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(key__icontains=search) |
                Q(title__icontains=search) |
                Q(description__icontains=search)
            )
        return qs
