"""
Enrollment Service — handles enrolment logic and validation.
"""

from django.db import transaction
from django.db.models import F

from formation.models import Enrollment, EnrollmentStatus, Course, Order, OrderStatus


class AlreadyEnrolled(Exception):
    pass


class PaymentRequired(Exception):
    """Raised when a paid course is enrolled without a settled order."""


def _course_is_free(course: Course) -> bool:
    """A course is free when explicitly flagged or priced at zero."""
    return bool(getattr(course, 'is_free', False)) or (course.price or 0) == 0


def has_entitlement(user, course: Course) -> bool:
    """
    True if the user is allowed to enrol in ``course`` right now.

    Free courses are always allowed. Paid courses require a PAID order owned by
    the same user that includes this course. This is the single source of truth
    for "did they pay?" — the payment provider, promo/gift codes and order
    workflow all converge on an Order row reaching ``PAID``.
    """
    if _course_is_free(course):
        return True
    return Order.objects.filter(
        user=user,
        status=OrderStatus.PAID,
        items__course=course,
    ).exists()


def self_enroll(user, course: Course) -> Enrollment:
    """
    Enrolment entry point for the public API.

    Enforces payment entitlement before delegating to :func:`enroll_user`. Any
    caller that has *already* verified payment (webhook, confirm-payment, admin
    force-enroll, gift claim) should call :func:`enroll_user` directly instead.

    Raises:
        PaymentRequired: paid course with no settled order for this user.
        AlreadyEnrolled: user already has an active enrolment.
    """
    if not has_entitlement(user, course):
        raise PaymentRequired(
            'This course requires a completed purchase before enrolment.'
        )
    return enroll_user(user, course)


def enroll_user(user, course: Course) -> Enrollment:
    """
    Enrol a user in a course.

    Trusted primitive: performs **no** payment check. Only call this from a
    context that has already established the user's entitlement. Public,
    user-driven enrolment must go through :func:`self_enroll`.

    Raises:
        AlreadyEnrolled: if user is already enrolled and active.
    """
    with transaction.atomic():
        existing = Enrollment.objects.filter(
            user=user, course=course,
        ).exclude(status=EnrollmentStatus.CANCELLED).first()

        if existing:
            raise AlreadyEnrolled('User is already enrolled in this course.')

        enrollment = Enrollment.objects.create(
            user=user,
            course=course,
            status=EnrollmentStatus.ACTIVE,
        )

        # Increment the student count on the course
        Course.objects.filter(pk=course.pk).update(students=F('students') + 1)

    return enrollment
