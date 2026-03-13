"""
Gamification Serializers — DRF serializers for API responses.
"""

from rest_framework import serializers

from gamefication.models import (
    AchievementDefinition,
    LeaderboardCache,
    UserAchievement,
    UserXP,
    XPTransaction,
    compute_level,
)


# ─── User XP Profile ────────────────────────────────────────────────────────

class UserXPSerializer(serializers.ModelSerializer):
    """Current user's XP profile with computed fields."""

    level_title = serializers.JSONField(read_only=True)
    xp_for_current_level = serializers.SerializerMethodField()
    xp_for_next_level = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = UserXP
        fields = [
            'total_xp', 'level', 'level_title',
            'xp_for_current_level', 'xp_for_next_level', 'progress',
            'streak_days', 'longest_streak', 'visible_on_leaderboard',
        ]

    def get_xp_for_current_level(self, obj):
        _lvl, _title, current, _nxt = compute_level(obj.total_xp)
        return current

    def get_xp_for_next_level(self, obj):
        _lvl, _title, _cur, nxt = compute_level(obj.total_xp)
        return nxt  # None if max level

    def get_progress(self, obj):
        """Progress percentage toward next level (0.0 – 100.0)."""
        _lvl, _title, current, nxt = compute_level(obj.total_xp)
        if nxt is None:
            return 100.0  # Max level
        span = nxt - current
        if span <= 0:
            return 100.0
        return round((obj.total_xp - current) / span * 100, 2)


# ─── XP Transaction History ─────────────────────────────────────────────────

class XPTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = XPTransaction
        fields = ['id', 'source', 'amount', 'reference_id', 'description', 'created_at']


# ─── Achievements ────────────────────────────────────────────────────────────

class AchievementSerializer(serializers.ModelSerializer):
    """Achievement definition with unlock status for the requesting user."""

    unlocked = serializers.SerializerMethodField()
    unlocked_at = serializers.SerializerMethodField()

    class Meta:
        model = AchievementDefinition
        fields = [
            'id', 'key', 'title', 'description', 'icon',
            'xp_reward', 'condition_type', 'condition_value',
            'unlocked', 'unlocked_at',
        ]

    def get_unlocked(self, obj):
        user = self.context.get('request', None)
        if user and hasattr(user, 'user'):
            user = user.user
        else:
            return False
        return UserAchievement.objects.filter(
            user=user, achievement=obj,
        ).exists()

    def get_unlocked_at(self, obj):
        user = self.context.get('request', None)
        if user and hasattr(user, 'user'):
            user = user.user
        else:
            return None
        try:
            ua = UserAchievement.objects.get(user=user, achievement=obj)
            return ua.unlocked_at
        except UserAchievement.DoesNotExist:
            return None


class AdminAchievementSerializer(serializers.ModelSerializer):
    """Full CRUD serializer for admin management of achievement definitions."""

    class Meta:
        model = AchievementDefinition
        fields = [
            'id', 'key', 'title', 'description', 'icon',
            'xp_reward', 'condition_type', 'condition_value',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ─── Leaderboard ─────────────────────────────────────────────────────────────

class LeaderboardUserSerializer(serializers.Serializer):
    """Nested user info for leaderboard entries."""
    id = serializers.UUIDField()
    name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)


class LeaderboardEntrySerializer(serializers.ModelSerializer):
    """Leaderboard entry with nested user info."""

    user = serializers.SerializerMethodField()

    class Meta:
        model = LeaderboardCache
        fields = ['rank', 'user', 'level', 'total_xp']

    def get_user(self, obj):
        return {
            'id': str(obj.user.id),
            'name': obj.user.display_name,
            'avatar_url': obj.user.avatar_display_url,
        }
