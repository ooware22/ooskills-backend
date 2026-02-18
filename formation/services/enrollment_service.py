"""
Enrollment Service — handles enrolment logic and validation.
"""

from django.db import transaction
from django.db.models import F

from formation.models import Enrollment, EnrollmentStatus, Course


class AlreadyEnrolled(Exception):
    pass


def enroll_user(user, course: Course) -> Enrollment:
    """
    Enrol a user in a course.

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
