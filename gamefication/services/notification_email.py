"""
Notification Email Service — sends email notifications for gamification events.

Uses Resend API (same as users/email.py).
Emails are sent in background threads to avoid blocking the main request.
"""

import logging
import threading

import resend
from django.conf import settings

from gamefication.models import LEVEL_TITLES_I18N

logger = logging.getLogger(__name__)


def _init_resend():
    """Initialise Resend API key from Django settings."""
    resend.api_key = settings.RESEND_API_KEY


def _send_in_background(func, *args, **kwargs):
    """Run an email function in a daemon thread."""
    threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True).start()


# =============================================================================
# LEVEL-UP EMAIL
# =============================================================================

def send_level_up_email(user, new_level: int, total_xp: int):
    """
    Send a congratulations email when a student levels up.

    Called from xp_service.award_xp() when leveled_up is True.
    """
    try:
        _init_resend()

        level_titles = LEVEL_TITLES_I18N.get(new_level, {})
        level_title_fr = level_titles.get('fr', f'Niveau {new_level}')
        name = user.first_name or user.display_name or user.email.split('@')[0]
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')

        subject = f"🎉 Félicitations ! Vous êtes maintenant {level_title_fr} - OOSkills"

        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #D4A843 0%, #E8C76A 100%); color: #1B2A4A; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .header h1 {{ margin: 0; font-size: 28px; }}
                .level-badge {{ display: inline-block; background: rgba(255,255,255,0.3); border-radius: 50%; width: 80px; height: 80px; line-height: 80px; font-size: 36px; margin-bottom: 15px; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .stats {{ background: white; border-radius: 8px; padding: 15px; margin: 15px 0; text-align: center; }}
                .stats .number {{ font-size: 24px; font-weight: bold; color: #D4A843; }}
                .stats .label {{ font-size: 12px; color: #999; }}
                .button {{ display: inline-block; background: #D4A843; color: #1B2A4A; padding: 15px 30px; text-decoration: none; border-radius: 8px; margin: 20px 0; font-weight: bold; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="level-badge">🏆</div>
                    <h1>Niveau {new_level} atteint !</h1>
                    <p style="margin: 5px 0 0; font-size: 16px;">{level_title_fr}</p>
                </div>
                <div class="content">
                    <p>Bonjour {name},</p>
                    <p>Félicitations ! Vous venez de passer au <strong>Niveau {new_level} — {level_title_fr}</strong> sur OOSkills ! 🎉</p>
                    <div class="stats">
                        <div class="number">{total_xp:,} XP</div>
                        <div class="label">XP Total accumulé</div>
                    </div>
                    <p>Continuez votre apprentissage pour débloquer encore plus de niveaux et de badges !</p>
                    <p style="text-align: center;">
                        <a href="{frontend_url}/dashboard" class="button">Voir mon profil</a>
                    </p>
                </div>
                <div class="footer">
                    <p>© 2024 OOSkills. Tous droits réservés.</p>
                </div>
            </div>
        </body>
        </html>
        """

        plain_message = f"""
Bonjour {name},

Félicitations ! Vous venez de passer au Niveau {new_level} — {level_title_fr} sur OOSkills ! 🎉

XP Total : {total_xp:,} XP

Continuez votre apprentissage pour débloquer encore plus de niveaux et de badges !

Voir mon profil : {frontend_url}/dashboard

© 2024 OOSkills. Tous droits réservés.
        """

        logger.info(f"[EMAIL] Sending level-up email to {user.email} (level {new_level})")
        r = resend.Emails.send({
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": [user.email],
            "subject": subject,
            "html": html_message,
            "text": plain_message,
        })
        logger.info(f"[EMAIL] Level-up email sent to {user.email} (id: {r.get('id', 'N/A')})")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] Error sending level-up email to {user.email}: {e}", exc_info=True)
        return False


def send_level_up_email_async(user, new_level: int, total_xp: int):
    """Send level-up email in a background thread."""
    _send_in_background(send_level_up_email, user, new_level, total_xp)


# =============================================================================
# CERTIFICATE EMAIL
# =============================================================================

def send_certificate_email(user, course_title: str, score: float, certificate_code: str):
    """
    Send a certificate notification email after passing the final quiz.

    Called from certificate_service.issue_certificate().
    """
    try:
        _init_resend()

        name = user.first_name or user.display_name or user.email.split('@')[0]
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')

        subject = f"🎓 Certificat obtenu — {course_title} - OOSkills"

        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .header h1 {{ margin: 0; font-size: 24px; }}
                .badge {{ display: inline-block; font-size: 48px; margin-bottom: 10px; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .cert-card {{ background: white; border: 2px solid #10b981; border-radius: 10px; padding: 20px; margin: 15px 0; text-align: center; }}
                .cert-card h3 {{ margin: 5px 0; color: #1B2A4A; }}
                .cert-card .score {{ font-size: 28px; font-weight: bold; color: #10b981; }}
                .cert-card .code {{ font-size: 12px; color: #999; margin-top: 10px; font-family: monospace; }}
                .button {{ display: inline-block; background: #10b981; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; margin: 20px 0; font-weight: bold; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="badge">🎓</div>
                    <h1>Certificat obtenu !</h1>
                </div>
                <div class="content">
                    <p>Bonjour {name},</p>
                    <p>Félicitations ! Vous avez réussi l'examen final et obtenu votre certificat pour :</p>
                    <div class="cert-card">
                        <h3>{course_title}</h3>
                        <div class="score">{score:.0f}%</div>
                        <p style="margin: 5px 0; color: #666;">Score obtenu</p>
                        <div class="code">Code : {certificate_code}</div>
                    </div>
                    <p>Vous pouvez consulter et télécharger votre certificat depuis votre tableau de bord.</p>
                    <p style="text-align: center;">
                        <a href="{frontend_url}/dashboard/certificates" class="button" style="color: white;">Voir mes certificats</a>
                    </p>
                </div>
                <div class="footer">
                    <p>© 2024 OOSkills. Tous droits réservés.</p>
                </div>
            </div>
        </body>
        </html>
        """

        plain_message = f"""
Bonjour {name},

Félicitations ! Vous avez réussi l'examen final et obtenu votre certificat pour :

{course_title}
Score : {score:.0f}%
Code : {certificate_code}

Vous pouvez consulter et télécharger votre certificat depuis votre tableau de bord.

Voir mes certificats : {frontend_url}/dashboard/certificates

© 2024 OOSkills. Tous droits réservés.
        """

        logger.info(f"[EMAIL] Sending certificate email to {user.email} for {course_title}")
        r = resend.Emails.send({
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": [user.email],
            "subject": subject,
            "html": html_message,
            "text": plain_message,
        })
        logger.info(f"[EMAIL] Certificate email sent to {user.email} (id: {r.get('id', 'N/A')})")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] Error sending certificate email to {user.email}: {e}", exc_info=True)
        return False


def send_certificate_email_async(user, course_title: str, score: float, certificate_code: str):
    """Send certificate email in a background thread."""
    _send_in_background(send_certificate_email, user, course_title, score, certificate_code)
