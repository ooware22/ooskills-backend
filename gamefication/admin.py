"""
Gamification Admin — register all gamification models.
"""

from django.contrib import admin

from gamefication.models import (
    AchievementDefinition,
    LeaderboardCache,
    UserAchievement,
    UserXP,
    XPTransaction,
)


# ─── UserXP ─────────────────────────────────────────────────────────────────

@admin.register(UserXP)
class UserXPAdmin(admin.ModelAdmin):
    list_display = ['user', 'total_xp', 'level', 'streak_days', 'streak_last_date', 'updated_at']
    list_filter = ['level']
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    raw_id_fields = ['user']


# ─── XP Transaction ─────────────────────────────────────────────────────────

@admin.register(XPTransaction)
class XPTransactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'source', 'amount', 'reference_id', 'created_at']
    list_filter = ['source', 'created_at']
    search_fields = ['user__email', 'reference_id', 'description']
    readonly_fields = ['id', 'created_at']
    raw_id_fields = ['user']
    date_hierarchy = 'created_at'


# ─── Achievement Definition ─────────────────────────────────────────────────

@admin.register(AchievementDefinition)
class AchievementDefinitionAdmin(admin.ModelAdmin):
    list_display = ['key', 'condition_type', 'condition_value', 'xp_reward', 'is_active']
    list_filter = ['condition_type', 'is_active']
    search_fields = ['key']
    readonly_fields = ['id', 'created_at', 'updated_at']


# ─── User Achievement ───────────────────────────────────────────────────────

@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ['user', 'achievement', 'unlocked_at']
    list_filter = ['unlocked_at']
    search_fields = ['user__email', 'achievement__key']
    readonly_fields = ['id']
    raw_id_fields = ['user', 'achievement']


# ─── Leaderboard Cache ──────────────────────────────────────────────────────

@admin.register(LeaderboardCache)
class LeaderboardCacheAdmin(admin.ModelAdmin):
    list_display = ['rank', 'user', 'period', 'total_xp', 'level', 'refreshed_at']
    list_filter = ['period']
    search_fields = ['user__email']
    readonly_fields = ['id', 'refreshed_at']
    raw_id_fields = ['user']
