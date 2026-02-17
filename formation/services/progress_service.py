"""
Progress Service — autosaves lesson progress with concurrency safety.

Uses select_for_update() to prevent lost updates when multiple requests
arrive simultaneously for the same user/lesson.
"""

from django.db import transaction
from django.utils import timezone

from formation.models import (
    Enrollment, EnrollmentStatus, Lesson, LessonProgress,
)


def autosave_progress(
    enrollment: Enrollment,
    lesson: Lesson,
    current_slide: int = 0,
    last_position: int = 0,
    time_spent_delta: int = 0,
    completed: bool = False,
) -> LessonProgress:
    """
    Create or update lesson progress atomically.

    Args:
        enrollment: Active enrollment instance
        lesson: The lesson being accessed
        current_slide: 0-based current slide index
        last_position: audio playback position in seconds
        time_spent_delta: additional seconds spent since last save
        completed: whether the student finished this lesson

    Returns:
        Updated LessonProgress instance
    """
    with transaction.atomic():
        progress, created = LessonProgress.objects.select_for_update().get_or_create(
            enrollment=enrollment,
            lesson=lesson,
            defaults={
                'current_slide': current_slide,
                'last_position': last_position,
                'time_spent': time_spent_delta,
                'completed': completed,
                'completed_at': timezone.now() if completed else None,
            },
        )

        if not created:
            progress.current_slide = max(progress.current_slide, current_slide)
            progress.last_position = last_position
            progress.time_spent += time_spent_delta
            if completed and not progress.completed:
                progress.completed = True
                progress.completed_at = timezone.now()
            progress.save()

    # Recalculate overall enrollment progress
    _recalculate_enrollment_progress(enrollment)
    return progress


def _recalculate_enrollment_progress(enrollment: Enrollment):
    """Recompute the enrolment-wide progress percentage."""
    total_lessons = Lesson.objects.filter(
        section__course=enrollment.course
    ).count()

    if total_lessons == 0:
        return

    completed_lessons = LessonProgress.objects.filter(
        enrollment=enrollment, completed=True,
    ).count()

    new_progress = round((completed_lessons / total_lessons) * 100, 2)
    enrollment.progress = new_progress

    if new_progress >= 100 and enrollment.status == EnrollmentStatus.ACTIVE:
        enrollment.status = EnrollmentStatus.COMPLETED
        enrollment.completed_at = timezone.now()
        # Certificate is now issued via the final quiz flow, not here.

    enrollment.save(update_fields=['progress', 'status', 'completed_at', 'updated_at'])

