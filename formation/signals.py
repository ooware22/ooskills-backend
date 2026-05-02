"""
Formation Signals — Cache invalidation on model changes.

Connected in FormationConfig.ready().
"""

import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from formation.models import (
    Category, Course, Section, Module, Lesson,
    Enrollment, Certificate, Quiz, QuizQuestion,
)

logger = logging.getLogger(__name__)


def _safe_invalidate(callback, context=""):
    """Run a cache invalidation callback, swallowing errors during cascades."""
    try:
        callback()
    except Exception:
        # During cascade deletes, parent objects may already be gone.
        # Don't let cache invalidation break the DB transaction.
        logger.debug("Cache invalidation skipped (%s) — likely cascade delete", context)


# ── Course ──────────────────────────────────────────────────────────────────

@receiver([post_save, post_delete], sender=Course)
def on_course_change(sender, instance, **kwargs):
    """Bust course list + detail caches when any course is modified."""
    _safe_invalidate(
        lambda: __import__('formation.cache', fromlist=['invalidate_course_caches']).invalidate_course_caches(instance.slug),
        context=f"course {instance.slug}",
    )


# ── Category ────────────────────────────────────────────────────────────────

@receiver([post_save, post_delete], sender=Category)
def on_category_change(sender, instance, **kwargs):
    def _do():
        from formation.cache import invalidate_categories, invalidate_course_list
        invalidate_categories()
        invalidate_course_list()
    _safe_invalidate(_do, context=f"category {instance.slug}")


# ── Section / Module / Lesson (children of Course) ──────────────────────────

@receiver([post_save, post_delete], sender=Section)
def on_section_change(sender, instance, **kwargs):
    def _do():
        from formation.cache import invalidate_course_caches, invalidate_sections
        slug = getattr(instance.course, 'slug', None) if instance.course_id else None
        invalidate_course_caches(slug)
        invalidate_sections()
    _safe_invalidate(_do, context="section")


@receiver([post_save, post_delete], sender=Module)
def on_module_change(sender, instance, **kwargs):
    def _do():
        from formation.cache import invalidate_course_caches, invalidate_sections
        slug = instance.section.course.slug if instance.section_id else None
        invalidate_course_caches(slug)
        invalidate_sections()
    _safe_invalidate(_do, context="module")


@receiver([post_save, post_delete], sender=Lesson)
def on_lesson_change(sender, instance, **kwargs):
    def _do():
        from formation.cache import invalidate_course_caches, invalidate_sections
        slug = instance.module.section.course.slug
        invalidate_course_caches(slug)
        invalidate_sections()
    _safe_invalidate(_do, context="lesson")


# ── Quiz / QuizQuestion ────────────────────────────────────────────────────

@receiver([post_save, post_delete], sender=Quiz)
def on_quiz_change(sender, instance, **kwargs):
    def _do():
        from formation.cache import invalidate_course_caches, invalidate_sections
        slug = instance.section.course.slug
        invalidate_course_caches(slug)
        invalidate_sections()
    _safe_invalidate(_do, context="quiz")


@receiver([post_save, post_delete], sender=QuizQuestion)
def on_quiz_question_change(sender, instance, **kwargs):
    def _do():
        from formation.cache import invalidate_course_caches
        slug = instance.quiz.section.course.slug
        invalidate_course_caches(slug)
    _safe_invalidate(_do, context="quiz_question")


# ── Enrollment ──────────────────────────────────────────────────────────────

@receiver(post_save, sender=Enrollment)
def on_enrollment_create(sender, instance, **kwargs):
    def _do():
        from formation.cache import invalidate_enrollment, invalidate_course_list
        invalidate_enrollment(instance.user_id, instance.course_id)
        invalidate_course_list()
    _safe_invalidate(_do, context="enrollment")

    # Push in-app notification on new enrollment (course purchased)
    if kwargs.get('created', False):
        try:
            from users.models import Notification, NotificationType
            course = instance.course
            title = getattr(course, 'title', None)
            if isinstance(title, dict):
                title = title.get('fr') or title.get('en') or 'Votre cours'
            Notification.push(
                instance.user,
                NotificationType.COURSE_PURCHASED,
                f"Cours acheté : {title or 'Votre cours'}",
                link=f"/courses/{getattr(course, 'slug', '')}/learn",
            )
        except Exception:
            pass  # Never break enrollment on notification failure


# ── Certificate ─────────────────────────────────────────────────────────────

@receiver(post_save, sender=Certificate)
def on_certificate_create(sender, instance, **kwargs):
    def _do():
        from formation.cache import invalidate_certificate
        if instance.code:
            invalidate_certificate(instance.code)
    _safe_invalidate(_do, context="certificate")

    # Push in-app notifications on new certificate
    if kwargs.get('created', False):
        try:
            from users.models import Notification, NotificationType
            enrollment = instance.enrollment
            course = enrollment.course
            course_title = getattr(course, 'title', None)
            if isinstance(course_title, dict):
                course_title = course_title.get('fr') or course_title.get('en') or 'votre cours'
            user = enrollment.user
            slug = getattr(course, 'slug', '')
            Notification.push(
                user, NotificationType.COURSE_COMPLETED,
                f"Cours terminé : {course_title or 'Votre cours'}",
                link=f"/courses/{slug}/learn",
            )
            Notification.push(
                user, NotificationType.CERTIFICATE_EARNED,
                f"Certificat obtenu : {course_title or 'Votre cours'}",
                link="/dashboard/certificates",
            )
        except Exception:
            pass  # Never break certificate creation on notification failure
