"""
Leaderboard Service — refresh and retrieve cached leaderboard rankings.

Uses LeaderboardCache to avoid expensive ORDER BY queries on every view.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from gamefication.models import (
    LeaderboardCache,
    LeaderboardPeriod,
    UserXP,
    XPTransaction,
)


def refresh_leaderboard(period: str = LeaderboardPeriod.ALLTIME):
    """
    Recompute leaderboard rankings and store in LeaderboardCache.

    For 'alltime': ranks by UserXP.total_xp
    For 'weekly': ranks by sum of XPTransactions in the last 7 days
    """
    if period == LeaderboardPeriod.ALLTIME:
        entries = _compute_alltime_rankings()
    elif period == LeaderboardPeriod.WEEKLY:
        entries = _compute_weekly_rankings()
    else:
        return

    cache_objects = []
    keep_user_ids = []
    for rank, entry in enumerate(entries, start=1):
        user_id = entry['user_id']
        keep_user_ids.append(user_id)
        cache_objects.append(
            LeaderboardCache(
                user_id=user_id,
                period=period,
                total_xp=entry['xp'],
                level=entry.get('level', 1),
                rank=rank,
            )
        )

    with transaction.atomic():
        # Upsert avoids duplicate key crashes when multiple refreshes run concurrently.
        if cache_objects:
            LeaderboardCache.objects.bulk_create(
                cache_objects,
                update_conflicts=True,
                update_fields=['total_xp', 'level', 'rank', 'refreshed_at'],
                unique_fields=['user', 'period'],
            )

            LeaderboardCache.objects.filter(period=period).exclude(
                user_id__in=keep_user_ids,
            ).delete()
        else:
            LeaderboardCache.objects.filter(period=period).delete()


def _compute_alltime_rankings() -> list[dict]:
    """Rank all users by total XP descending (only visible users)."""
    from django.db.models import F
    return list(
        UserXP.objects.filter(total_xp__gt=0, visible_on_leaderboard=True)
        .order_by('-total_xp')
        .values('user_id', 'level')
        .annotate(xp=F('total_xp'))
        [:200]  # Cap at top 200
    )


def _compute_weekly_rankings() -> list[dict]:
    """Rank users by XP earned in the last 7 days."""
    week_ago = timezone.now() - timedelta(days=7)

    weekly_xp = (
        XPTransaction.objects
        .filter(
            created_at__gte=week_ago,
            amount__gt=0,
            user__xp_profile__visible_on_leaderboard=True,
        )
        .values('user_id')
        .annotate(xp=Sum('amount'))
        .order_by('-xp')
        [:200]
    )

    # Enrich with current level from UserXP
    user_levels = dict(
        UserXP.objects.filter(
            user_id__in=[e['user_id'] for e in weekly_xp]
        ).values_list('user_id', 'level')
    )

    results = []
    for entry in weekly_xp:
        results.append({
            'user_id': entry['user_id'],
            'xp': entry['xp'],
            'level': user_levels.get(entry['user_id'], 1),
        })

    return results


def get_leaderboard(period: str = LeaderboardPeriod.ALLTIME):
    """
    Retrieve cached leaderboard entries.
    Returns a queryset of LeaderboardCache ordered by rank.
    """
    return LeaderboardCache.objects.filter(
        period=period,
    ).select_related('user').order_by('rank')
