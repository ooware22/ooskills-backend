"""
XP Service — core XP awarding, level computation, and streak tracking.

All mutations use atomic transactions. Called by signals when students
complete lessons, pass quizzes, etc.
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from gamefication.models import UserXP, XPTransaction, compute_level


def award_xp(
    user,
    amount: int,
    source: str,
    reference_id: str = '',
    description: str = '',
) -> dict:
    """
    Award XP to a user atomically.

    Creates an XPTransaction, updates UserXP.total_xp, recalculates
    level, updates streak, and triggers achievement checks.

    Args:
        user: User instance
        amount: XP to award (positive = gain)
        source: XPSourceType value (lesson, quiz, final_quiz, etc.)
        reference_id: UUID/identifier of the source object
        description: Human-readable description

    Returns:
        dict with keys: new_xp, new_level, leveled_up, level_title,
                        streak_days, achievements_unlocked
    """
    from gamefication.services.achievement_service import check_achievements

    with transaction.atomic():
        # Get or create UserXP profile
        user_xp, _created = UserXP.objects.select_for_update().get_or_create(
            user=user,
            defaults={
                'total_xp': 0,
                'level': 1,
                'level_title': {'en': 'Beginner', 'fr': 'Débutant', 'ar': 'مبتدئ'},
            },
        )

        old_level = user_xp.level

        # Create audit log entry
        XPTransaction.objects.create(
            user=user,
            source=source,
            amount=amount,
            reference_id=str(reference_id),
            description=description,
        )

        # Update total XP
        user_xp.total_xp = max(0, user_xp.total_xp + amount)

        # Recalculate level
        user_xp.recalculate_level()

        # Update streak
        _update_streak(user_xp)

        user_xp.save()

        leveled_up = user_xp.level > old_level

    # Check achievements (outside the XP transaction to avoid deadlocks)
    achievements_unlocked = check_achievements(user)

    return {
        'new_xp': user_xp.total_xp,
        'new_level': user_xp.level,
        'level_title': user_xp.level_title,
        'leveled_up': leveled_up,
        'streak_days': user_xp.streak_days,
        'achievements_unlocked': achievements_unlocked,
    }


def _update_streak(user_xp: UserXP):
    """Increment or reset the daily streak."""
    today = timezone.now().date()

    if user_xp.streak_last_date is None:
        # First activity ever
        user_xp.streak_days = 1
        user_xp.streak_last_date = today
    elif user_xp.streak_last_date == today:
        # Already counted today, no change
        pass
    elif user_xp.streak_last_date == today - timedelta(days=1):
        # Consecutive day
        user_xp.streak_days += 1
        user_xp.streak_last_date = today
    else:
        # Streak broken — reset
        user_xp.streak_days = 1
        user_xp.streak_last_date = today

    # Maintain record
    if user_xp.streak_days > user_xp.longest_streak:
        user_xp.longest_streak = user_xp.streak_days


def get_or_create_xp_profile(user) -> UserXP:
    """Get or create a user's XP profile with defaults."""
    user_xp, _created = UserXP.objects.get_or_create(
        user=user,
        defaults={
            'total_xp': 0,
            'level': 1,
            'level_title': {'en': 'Beginner', 'fr': 'Débutant', 'ar': 'مبتدئ'},
        },
    )
    return user_xp
