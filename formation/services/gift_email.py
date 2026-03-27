"""
Gift Email Notification Service

Sends email to gift recipients with claim link via Resend.
"""

import logging
from django.conf import settings
import resend

logger = logging.getLogger(__name__)


def _init_resend():
    """Initialise Resend API key from Django settings."""
    resend.api_key = settings.RESEND_API_KEY


def send_gift_email(recipient_email, sender_name, course_title, gift_code, message=''):
    """
    Send gift notification email to recipient via Resend.

    Args:
        recipient_email: Recipient's email address
        sender_name: Display name of the sender
        course_title: Title of the gifted course
        gift_code: The gift claim code
        message: Optional personal message from sender

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        _init_resend()

        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        claim_url = f"{frontend_url}/gift/claim?code={gift_code}"

        subject = f"🎁 {sender_name} vous offre une formation sur OOSkills !"

        message_block = ''
        message_plain = ''
        if message:
            message_block = f'''
                    <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; border-radius: 5px; margin: 15px 0;">
                        <p style="margin: 0; font-style: italic; color: #856404;">"{message}"</p>
                        <p style="margin: 5px 0 0; font-size: 12px; color: #856404;">— {sender_name}</p>
                    </div>
            '''
            message_plain = f'\nMessage de {sender_name}: "{message}"\n'

        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #d4a843 0%, #b8960f 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #d4a843; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; margin: 20px 0; font-weight: bold; font-size: 16px; }}
                .gift-code {{ background: #eee; padding: 12px 20px; border-radius: 8px; font-family: monospace; font-size: 18px; font-weight: bold; letter-spacing: 2px; text-align: center; color: #1a1a2e; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">🎁 Vous avez reçu un cadeau !</h1>
                </div>
                <div class="content">
                    <p>Bonjour,</p>
                    <p><strong>{sender_name}</strong> vous offre la formation :</p>
                    <h2 style="color: #1a1a2e; text-align: center; margin: 20px 0;">{course_title}</h2>
                    {message_block}
                    <p>Votre code cadeau :</p>
                    <div class="gift-code">{gift_code}</div>
                    <p style="text-align: center;">
                        <a href="{claim_url}" class="button" style="color: white;">Réclamer mon cadeau</a>
                    </p>
                    <p>Ou copiez ce lien dans votre navigateur :</p>
                    <p style="word-break: break-all; background: #eee; padding: 10px; border-radius: 5px; font-size: 12px;">{claim_url}</p>
                    <p><strong>Ce cadeau expire dans 90 jours.</strong></p>
                </div>
                <div class="footer">
                    <p>© 2026 OOSkills. Tous droits réservés.</p>
                </div>
            </div>
        </body>
        </html>
        """

        plain_message = f"""
Bonjour,

{sender_name} vous offre la formation "{course_title}" sur OOSkills !
{message_plain}
Votre code cadeau : {gift_code}

Réclamez votre cadeau ici : {claim_url}

Ce cadeau expire dans 90 jours.

© 2026 OOSkills. Tous droits réservés.
        """

        logger.info(f"[EMAIL] Sending gift email to {recipient_email} via Resend")
        r = resend.Emails.send({
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": [recipient_email],
            "subject": subject,
            "html": html_message,
            "text": plain_message,
        })
        logger.info(f"[EMAIL] Gift email sent successfully to {recipient_email} (id: {r.get('id', 'N/A')})")

        return True
    except Exception as e:
        logger.error(f"[EMAIL] Error sending gift email to {recipient_email}: {type(e).__name__}: {e}", exc_info=True)
        return False
