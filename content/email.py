"""
Contact Form Notification Email Service

Best-effort notification sent to the site's contact inbox when a visitor
submits the Contact Us form. The ContactMessage row (see models.py) is the
source of truth — a failure here never loses the message, since it's already
saved to the database before this is called.
"""

import logging
from django.conf import settings
import resend

logger = logging.getLogger(__name__)


def _init_resend():
    """Initialise Resend API key from Django settings."""
    resend.api_key = settings.RESEND_API_KEY


def send_contact_notification(contact_message):
    """
    Notify the configured contact inbox about a new form submission.

    Args:
        contact_message: ContactMessage instance (already saved)

    Returns:
        bool: True if sent successfully, False otherwise (never raises)
    """
    notify_to = settings.CONTACT_NOTIFICATION_EMAIL
    if not notify_to:
        logger.warning("[EMAIL] CONTACT_NOTIFICATION_EMAIL not configured — skipping contact notification")
        return False

    try:
        _init_resend()

        subject = f"[OOSkills Contact] {contact_message.subject}"

        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #1a2332;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a2332;">New Contact Form Message</h2>
                <p><strong>From:</strong> {contact_message.name} &lt;{contact_message.email}&gt;</p>
                <p><strong>Subject:</strong> {contact_message.subject}</p>
                <p><strong>Message:</strong></p>
                <p style="background: #f5f5f5; padding: 15px; border-radius: 5px; white-space: pre-wrap;">{contact_message.message}</p>
                <p style="color: #888; font-size: 12px; margin-top: 20px;">
                    View and manage all messages in the admin panel.
                </p>
            </div>
        </body>
        </html>
        """

        plain_message = f"""
New contact form message

From: {contact_message.name} <{contact_message.email}>
Subject: {contact_message.subject}

{contact_message.message}

View and manage all messages in the admin panel.
        """

        logger.info(f"[EMAIL] Sending contact notification to {notify_to} via Resend")
        r = resend.Emails.send({
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": [notify_to],
            "reply_to": contact_message.email,
            "subject": subject,
            "html": html_message,
            "text": plain_message,
        })
        logger.info(f"[EMAIL] Contact notification sent successfully (id: {r.get('id', 'N/A')})")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] Error sending contact notification: {type(e).__name__}: {e}", exc_info=True)
        return False
