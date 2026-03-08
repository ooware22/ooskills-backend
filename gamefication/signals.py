"""
Gamification Signals — auto-award XP on learning events.

Listens to post_save signals on LessonProgress, QuizAttempt,
FinalQuizAttempt, and Enrollment from the formation app.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from gamefication.models import XPSourceType

logger = logging.getLogger(__name__)

# XP amounts for each event type
LESSON_COMPLETE_XP = 10
ENROLLMENT_XP = 5


@receiver(post_save, sender='formation.LessonProgress')
def on_lesson_completed(sender, instance, created, **kwargs):
    """Award XP when a lesson is marked as completed."""
    if not instance.completed:
        return

    # Avoid double-awarding: check if we already gave XP for this lesson
    from gamefication.models import XPTransaction
    user = instance.enrollment.user

    already_awarded = XPTransaction.objects.filter(
        user=user,
        source=XPSourceType.LESSON,
        reference_id=str(instance.lesson_id),
    ).exists()

    if already_awarded:
        return

    from gamefication.services.xp_service import award_xp
    try:
        result = award_xp(
            user=user,
            amount=LESSON_COMPLETE_XP,
            source=XPSourceType.LESSON,
            reference_id=str(instance.lesson_id),
            description=f'Lesson completed: {instance.lesson}',
        )
        logger.info(
            f'XP awarded: {user} +{LESSON_COMPLETE_XP} XP (lesson). '
            f'Total: {result["new_xp"]}, Level: {result["new_level"]}'
        )
    except Exception as e:
        logger.error(f'Failed to award lesson XP for {user}: {e}')


@receiver(post_save, sender='formation.QuizAttempt')
def on_quiz_passed(sender, instance, created, **kwargs):
    """Award XP when a quiz is passed (first pass only)."""
    if not created or not instance.passed or instance.xp_earned <= 0:
        return

    from gamefication.models import XPTransaction
    user = instance.enrollment.user

    # Only award XP for the first passing attempt of this quiz
    already_awarded = XPTransaction.objects.filter(
        user=user,
        source=XPSourceType.QUIZ,
        reference_id=str(instance.quiz_id),
    ).exists()

    if already_awarded:
        return

    from gamefication.services.xp_service import award_xp
    try:
        result = award_xp(
            user=user,
            amount=instance.xp_earned,
            source=XPSourceType.QUIZ,
            reference_id=str(instance.quiz_id),
            description=f'Quiz passed: {instance.quiz}',
        )
        logger.info(
            f'XP awarded: {user} +{instance.xp_earned} XP (quiz). '
            f'Total: {result["new_xp"]}, Level: {result["new_level"]}'
        )
    except Exception as e:
        logger.error(f'Failed to award quiz XP for {user}: {e}')


@receiver(post_save, sender='formation.FinalQuizAttempt')
def on_final_quiz_passed(sender, instance, created, **kwargs):
    """Award XP when a final quiz is passed (first pass only)."""
    if not created or not instance.passed or instance.xp_earned <= 0:
        return

    from gamefication.models import XPTransaction
    user = instance.enrollment.user

    already_awarded = XPTransaction.objects.filter(
        user=user,
        source=XPSourceType.FINAL_QUIZ,
        reference_id=str(instance.final_quiz_id),
    ).exists()

    if already_awarded:
        return

    from gamefication.services.xp_service import award_xp
    try:
        result = award_xp(
            user=user,
            amount=instance.xp_earned,
            source=XPSourceType.FINAL_QUIZ,
            reference_id=str(instance.final_quiz_id),
            description=f'Final quiz passed',
        )
        logger.info(
            f'XP awarded: {user} +{instance.xp_earned} XP (final_quiz). '
            f'Total: {result["new_xp"]}, Level: {result["new_level"]}'
        )
    except Exception as e:
        logger.error(f'Failed to award final quiz XP for {user}: {e}')


@receiver(post_save, sender='formation.Enrollment')
def on_enrollment_created(sender, instance, created, **kwargs):
    """Award small XP bonus when a user enrolls in a course."""
    if not created:
        return

    from gamefication.services.xp_service import award_xp
    try:
        result = award_xp(
            user=instance.user,
            amount=ENROLLMENT_XP,
            source=XPSourceType.ENROLLMENT,
            reference_id=str(instance.id),
            description=f'Enrolled in: {instance.course}',
        )
        logger.info(
            f'XP awarded: {instance.user} +{ENROLLMENT_XP} XP (enrollment). '
            f'Total: {result["new_xp"]}, Level: {result["new_level"]}'
        )
    except Exception as e:
        logger.error(f'Failed to award enrollment XP for {instance.user}: {e}')
