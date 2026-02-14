"""
Certificate Service — issues certificates upon course completion.
"""

import secrets

from formation.models import Certificate, Enrollment, EnrollmentStatus


class CourseNotCompleted(Exception):
    pass


class CertificateAlreadyIssued(Exception):
    pass


def issue_certificate(enrollment: Enrollment, score: float = 0) -> Certificate:
    """
    Issue a certificate for a completed course.

    Args:
        enrollment: Must be in COMPLETED status.
        score: The final score to record.

    Returns:
        Certificate instance.

    Raises:
        CourseNotCompleted: if enrolment is not marked completed.
        CertificateAlreadyIssued: if certificate already exists.
    """
    if enrollment.status != EnrollmentStatus.COMPLETED:
        raise CourseNotCompleted(
            'Cannot issue certificate — course not completed.'
        )

    if Certificate.objects.filter(
        user=enrollment.user, course=enrollment.course
    ).exists():
        raise CertificateAlreadyIssued(
            'Certificate already issued for this course.'
        )

    code = f'OOS-{secrets.token_hex(6).upper()}'
    return Certificate.objects.create(
        user=enrollment.user,
        course=enrollment.course,
        score=score,
        code=code,
    )
