"""
Sharing Service — token generation, validation, and access rules.
"""

import secrets

from django.utils import timezone
from django.db import transaction

from formation.models import ShareToken, Course


def create_share_token(
    course: Course,
    user,
    visibility: str = 'token',
    max_uses: int = 0,
    expires_in_days: int | None = None,
) -> ShareToken:
    """Create a new share token for a course."""
    expires_at = None
    if expires_in_days:
        expires_at = timezone.now() + timezone.timedelta(days=expires_in_days)

    return ShareToken.objects.create(
        course=course,
        created_by=user,
        token=secrets.token_urlsafe(32),
        visibility=visibility,
        max_uses=max_uses,
        expires_at=expires_at,
    )


def validate_and_consume_token(token_str: str) -> ShareToken | None:
    """
    Validate a share token and increment usage counter atomically.

    Returns the ShareToken if valid, else None.
    """
    with transaction.atomic():
        try:
            share = ShareToken.objects.select_for_update().get(
                token=token_str, is_active=True,
            )
        except ShareToken.DoesNotExist:
            return None

        if not share.is_valid:
            return None

        share.uses_count += 1
        share.save(update_fields=['uses_count'])
        return share
