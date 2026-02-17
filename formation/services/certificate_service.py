"""
Certificate Service — issues certificates upon passing the final quiz.

Generates a PDF certificate and uploads it to Supabase Storage.
"""

import secrets
import logging

from formation.models import Certificate, Enrollment, EnrollmentStatus
from formation.services.pdf_service import generate_certificate_pdf

logger = logging.getLogger(__name__)


class CourseNotCompleted(Exception):
    pass


class CertificateAlreadyIssued(Exception):
    pass


def issue_certificate(enrollment: Enrollment, score: float = 0) -> Certificate:
    """
    Issue a certificate for a completed course.

    Generates a PDF and attempts to upload it to Supabase Storage.
    Falls back gracefully if upload fails.

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

    # Generate PDF
    student_name = getattr(enrollment.user, 'full_name', '') or str(enrollment.user)
    course_title = enrollment.course.title or '(untitled)'
    pdf_bytes = generate_certificate_pdf(
        student_name=student_name,
        course_title=course_title,
        score=score,
        code=code,
    )

    # Upload to Supabase Storage
    pdf_url = ''
    try:
        pdf_url = _upload_pdf_to_supabase(
            pdf_bytes=pdf_bytes,
            code=code,
            course_id=str(enrollment.course.id),
        )
    except Exception as e:
        logger.warning(f'Failed to upload certificate PDF to Supabase: {e}')

    return Certificate.objects.create(
        user=enrollment.user,
        course=enrollment.course,
        score=score,
        code=code,
        pdf_url=pdf_url,
    )


def _upload_pdf_to_supabase(
    pdf_bytes: bytes,
    code: str,
    course_id: str,
) -> str:
    """
    Upload PDF bytes to Supabase Storage and return the public URL.

    Uploads to: certificates/<course_id>/<code>.pdf
    """
    from django.conf import settings
    from supabase import create_client

    supabase_url = getattr(settings, 'SUPABASE_URL', '')
    supabase_key = getattr(settings, 'SUPABASE_SERVICE_ROLE_KEY', '') or getattr(settings, 'SUPABASE_KEY', '')

    if not supabase_url or not supabase_key:
        raise RuntimeError('Supabase credentials not configured.')

    client = create_client(supabase_url, supabase_key)
    bucket_name = 'certificates'
    file_path = f'{course_id}/{code}.pdf'

    client.storage.from_(bucket_name).upload(
        path=file_path,
        file=pdf_bytes,
        file_options={'content-type': 'application/pdf'},
    )

    # Return the public URL
    result = client.storage.from_(bucket_name).get_public_url(file_path)
    return result
