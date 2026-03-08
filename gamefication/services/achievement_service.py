"""
Achievement Service — checks conditions and unlocks achievements.

Called after every XP award to see if any new achievements are met.
"""

from django.db import transaction

from gamefication.models import (
    AchievementDefinition,
    ConditionType,
    UserAchievement,
    UserXP,
    XPSourceType,
    XPTransaction,
)


def check_achievements(user) -> list[dict]:
    """
    Check all active achievement definitions against the user's stats.
    Unlock any newly met achievements and award their XP bonus.

    Returns:
        List of newly unlocked achievements as dicts:
        [{'key': '...', 'title': {...}, 'xp_reward': N}, ...]
    """
    # Get all active definitions
    definitions = AchievementDefinition.objects.filter(is_active=True)

    # Get already unlocked achievement IDs
    unlocked_ids = set(
        UserAchievement.objects.filter(user=user)
        .values_list('achievement_id', flat=True)
    )

    # Fetch user stats (lazily, only what's needed)
    stats = _get_user_stats(user)

    newly_unlocked = []

    for defn in definitions:
        if defn.id in unlocked_ids:
            continue  # Already unlocked

        if _condition_met(defn, stats):
            with transaction.atomic():
                # Double-check to prevent race condition
                _, created = UserAchievement.objects.get_or_create(
                    user=user,
                    achievement=defn,
                )
                if created:
                    # Award achievement XP (without re-triggering achievement check)
                    _award_achievement_xp(user, defn)
                    newly_unlocked.append({
                        'key': defn.key,
                        'title': defn.title,
                        'xp_reward': defn.xp_reward,
                    })

    return newly_unlocked


def _condition_met(defn: AchievementDefinition, stats: dict) -> bool:
    """Check if a single achievement condition is met."""
    ct = defn.condition_type
    val = defn.condition_value

    if ct == ConditionType.LESSONS_COMPLETED:
        return stats.get('lessons_completed', 0) >= val
    elif ct == ConditionType.QUIZZES_PASSED:
        return stats.get('quizzes_passed', 0) >= val
    elif ct == ConditionType.COURSES_COMPLETED:
        return stats.get('courses_completed', 0) >= val
    elif ct == ConditionType.STREAK_DAYS:
        return stats.get('streak_days', 0) >= val
    elif ct == ConditionType.TOTAL_XP:
        return stats.get('total_xp', 0) >= val
    elif ct == ConditionType.PERFECT_QUIZ:
        return stats.get('perfect_quizzes', 0) >= val

    return False


def _get_user_stats(user) -> dict:
    """Gather all stats needed for achievement condition checking."""
    from formation.models import (
        LessonProgress,
        QuizAttempt,
        Enrollment,
        EnrollmentStatus,
    )

    lessons_completed = LessonProgress.objects.filter(
        enrollment__user=user,
        completed=True,
    ).count()

    quizzes_passed = QuizAttempt.objects.filter(
        enrollment__user=user,
        passed=True,
    ).count()

    courses_completed = Enrollment.objects.filter(
        user=user,
        status=EnrollmentStatus.COMPLETED,
    ).count()

    perfect_quizzes = QuizAttempt.objects.filter(
        enrollment__user=user,
        score=100,
    ).count()

    # XP and streak from UserXP profile
    try:
        user_xp = UserXP.objects.get(user=user)
        total_xp = user_xp.total_xp
        streak_days = user_xp.streak_days
    except UserXP.DoesNotExist:
        total_xp = 0
        streak_days = 0

    return {
        'lessons_completed': lessons_completed,
        'quizzes_passed': quizzes_passed,
        'courses_completed': courses_completed,
        'perfect_quizzes': perfect_quizzes,
        'total_xp': total_xp,
        'streak_days': streak_days,
    }


def _award_achievement_xp(user, defn: AchievementDefinition):
    """Award XP for unlocking an achievement (without re-triggering check)."""
    if defn.xp_reward <= 0:
        return

    user_xp, _ = UserXP.objects.select_for_update().get_or_create(
        user=user,
        defaults={
            'total_xp': 0,
            'level': 1,
            'level_title': {'en': 'Beginner', 'fr': 'Débutant', 'ar': 'مبتدئ'},
        },
    )

    XPTransaction.objects.create(
        user=user,
        source=XPSourceType.ACHIEVEMENT,
        amount=defn.xp_reward,
        reference_id=str(defn.id),
        description=f'Achievement: {defn.key}',
    )

    user_xp.total_xp += defn.xp_reward
    user_xp.recalculate_level()
    user_xp.save()
