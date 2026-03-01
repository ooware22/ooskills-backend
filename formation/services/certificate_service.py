"""
Certificate Service — issues certificates upon passing the final quiz.

PDF generation and Supabase storage are handled entirely by the frontend.
This service only creates and persists the Certificate database record.
"""

import secrets
import logging

from formation.models import Certificate, Enrollment, EnrollmentStatus

logger = logging.getLogger(__name__)


class CourseNotCompleted(Exception):
    pass


class CertificateAlreadyIssued(Exception):
    pass


def issue_certificate(enrollment: Enrollment, score: float = 0) -> Certificate:
    """
    Issue a certificate for a completed course.

    Args:
        enrollment: Must be in COMPLETED status.
        score: The final quiz score to record.

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
        pdf_url='',
    )
