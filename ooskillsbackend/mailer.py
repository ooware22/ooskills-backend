"""
Single exit point for outgoing e-mail (Resend).

Every module that sends mail goes through :func:`send_email` instead of calling
``resend.Emails.send`` directly, so one setting can keep a non-production
environment from mailing real people.

``EMAIL_RECIPIENT_ALLOWLIST`` (comma-separated, from the environment):

* empty (production)  → every message is sent;
* ``@ooskills.com,qa@example.org`` (staging) → only addresses on those domains
  or those exact addresses receive mail; anything else is logged and dropped.
"""

import logging

import resend
from django.conf import settings

logger = logging.getLogger(__name__)


def _is_allowed(address: str, allowlist) -> bool:
    address = (address or '').strip().lower()
    for entry in allowlist:
        entry = entry.strip().lower()
        if not entry:
            continue
        if entry.startswith('@'):
            if address.endswith(entry):
                return True
        elif address == entry:
            return True
    return False


def send_email(params: dict) -> dict:
    """Send one message through Resend, honouring the recipient allowlist."""
    allowlist = getattr(settings, 'EMAIL_RECIPIENT_ALLOWLIST', None) or []
    if allowlist:
        recipients = params.get('to') or []
        if isinstance(recipients, str):
            recipients = [recipients]
        kept = [a for a in recipients if _is_allowed(a, allowlist)]
        if not kept:
            logger.info(
                '[EMAIL] Not sent (%s environment, recipient not on '
                'EMAIL_RECIPIENT_ALLOWLIST): subject=%r',
                getattr(settings, 'ENVIRONMENT', '?'), params.get('subject'),
            )
            return {'id': 'suppressed'}
        params = {**params, 'to': kept}
    return resend.Emails.send(params)
