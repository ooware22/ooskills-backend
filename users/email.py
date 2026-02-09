"""
Email Utilities for OOSkills Platform

Provides functions for sending verification and notification emails.
"""

import secrets
from datetime import timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone


def generate_verification_token(user):
    """
    Generate a verification token for the user.
    
    Args:
        user: User instance
        
    Returns:
        EmailVerificationToken instance
    """
    from .models import EmailVerificationToken
    
    # Invalidate previous tokens
    EmailVerificationToken.objects.filter(
        user=user,
        is_used=False
    ).update(is_used=True)
    
    # Create new token
    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(
        hours=getattr(settings, 'EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS', 24)
    )
    
    verification_token = EmailVerificationToken.objects.create(
        user=user,
        token=token,
        expires_at=expires_at
    )
    
    return verification_token


def get_verification_url(token):
    """Get the frontend verification URL."""
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
    return f"{frontend_url}/verify-email?token={token}"


def send_verification_email(user):
    """
    Send verification email to user.
    
    Args:
        user: User instance
        
    Returns:
        True if sent successfully, False otherwise
    """
    try:
        # Generate token
        verification_token = generate_verification_token(user)
        verification_url = get_verification_url(verification_token.token)
        
        # Build email content
        subject = "Vérifiez votre adresse email - OOSkills"
        
        # HTML content
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .button:hover {{ background: #5a67d8; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Bienvenue sur OOSkills!</h1>
                </div>
                <div class="content">
                    <p>Bonjour {user.first_name or user.email.split('@')[0]},</p>
                    <p>Merci de vous être inscrit sur OOSkills. Pour activer votre compte, veuillez cliquer sur le bouton ci-dessous:</p>
                    <p style="text-align: center;">
                        <a href="{verification_url}" class="button" style="color: white;">Vérifier mon email</a>
                    </p>
                    <p>Ou copiez ce lien dans votre navigateur:</p>
                    <p style="word-break: break-all; background: #eee; padding: 10px; border-radius: 5px; font-size: 12px;">{verification_url}</p>
                    <p><strong>Ce lien expire dans 24 heures.</strong></p>
                    <p>Si vous n'avez pas créé de compte sur OOSkills, ignorez simplement cet email.</p>
                </div>
                <div class="footer">
                    <p>© 2024 OOSkills. Tous droits réservés.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text fallback
        plain_message = f"""
Bonjour {user.first_name or user.email.split('@')[0]},

Merci de vous être inscrit sur OOSkills. Pour activer votre compte, veuillez cliquer sur le lien ci-dessous:

{verification_url}

Ce lien expire dans 24 heures.

Si vous n'avez pas créé de compte sur OOSkills, ignorez simplement cet email.

© 2024 OOSkills. Tous droits réservés.
        """
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True
    except Exception as e:
        print(f"Error sending verification email: {e}")
        return False


def send_welcome_email(user):
    """
    Send welcome email after verification.
    
    Args:
        user: User instance
    """
    try:
        subject = "Bienvenue sur OOSkills!"
        
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎉 Votre compte est activé!</h1>
                </div>
                <div class="content">
                    <p>Bonjour {user.first_name or user.email.split('@')[0]},</p>
                    <p>Votre compte OOSkills est maintenant activé. Vous pouvez commencer à explorer nos formations.</p>
                    <p style="text-align: center;">
                        <a href="{settings.FRONTEND_URL}" class="button" style="color: white;">Commencer</a>
                    </p>
                    <p>À bientôt sur OOSkills!</p>
                </div>
                <div class="footer">
                    <p>© 2024 OOSkills. Tous droits réservés.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
Bonjour {user.first_name or user.email.split('@')[0]},

Votre compte OOSkills est maintenant activé. Vous pouvez commencer à explorer nos formations.

Visitez: {settings.FRONTEND_URL}

À bientôt sur OOSkills!

© 2024 OOSkills. Tous droits réservés.
        """
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=True,
        )
        
        return True
    except Exception:
        return False


def verify_email_token(token):
    """
    Verify email token and activate user.
    
    Args:
        token: Token string
        
    Returns:
        Tuple of (success: bool, user: User or None, error_message: str)
    """
    from .models import EmailVerificationToken
    
    try:
        verification_token = EmailVerificationToken.objects.select_related('user').get(
            token=token
        )
    except EmailVerificationToken.DoesNotExist:
        return False, None, "Token invalide."
    
    if verification_token.is_used:
        return False, verification_token.user, "Ce lien a déjà été utilisé."
    
    if verification_token.is_expired:
        return False, verification_token.user, "Ce lien a expiré. Veuillez demander un nouveau lien."
    
    # Activate user
    if verification_token.use_token():
        # Send welcome email in background (non-blocking)
        import threading
        threading.Thread(target=send_welcome_email, args=(verification_token.user,), daemon=True).start()
        return True, verification_token.user, "Email vérifié avec succès!"
    
    return False, None, "Erreur lors de la vérification."


# =============================================================================
# PASSWORD RESET FUNCTIONS
# =============================================================================

def generate_password_reset_token(user):
    """
    Generate a password reset token for the user.
    
    Args:
        user: User instance
        
    Returns:
        PasswordResetToken instance
    """
    from .models import PasswordResetToken
    
    # Invalidate previous tokens
    PasswordResetToken.objects.filter(
        user=user,
        is_used=False
    ).update(is_used=True)
    
    # Create new token
    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(
        hours=getattr(settings, 'PASSWORD_RESET_TOKEN_EXPIRY_HOURS', 1)
    )
    
    reset_token = PasswordResetToken.objects.create(
        user=user,
        token=token,
        expires_at=expires_at
    )
    
    return reset_token


def get_password_reset_url(token):
    """Get the frontend password reset URL."""
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
    return f"{frontend_url}/reset-password?token={token}"


def send_password_reset_email(user):
    """
    Send password reset email to user.
    
    Args:
        user: User instance
        
    Returns:
        True if sent successfully, False otherwise
    """
    try:
        # Generate token
        reset_token = generate_password_reset_token(user)
        reset_url = get_password_reset_url(reset_token.token)
        
        # Build email content
        subject = "Réinitialisation de votre mot de passe - OOSkills"
        
        # HTML content
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .button:hover {{ background: #5a67d8; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Réinitialisation du mot de passe</h1>
                </div>
                <div class="content">
                    <p>Bonjour {user.first_name or user.email.split('@')[0]},</p>
                    <p>Vous avez demandé la réinitialisation de votre mot de passe sur OOSkills. Cliquez sur le bouton ci-dessous pour créer un nouveau mot de passe:</p>
                    <p style="text-align: center;">
                        <a href="{reset_url}" class="button" style="color: white;">Réinitialiser mon mot de passe</a>
                    </p>
                    <p>Ou copiez ce lien dans votre navigateur:</p>
                    <p style="word-break: break-all; background: #eee; padding: 10px; border-radius: 5px; font-size: 12px;">{reset_url}</p>
                    <p><strong>Ce lien expire dans 1 heure.</strong></p>
                    <p>Si vous n'avez pas demandé la réinitialisation de votre mot de passe, ignorez simplement cet email. Votre mot de passe restera inchangé.</p>
                </div>
                <div class="footer">
                    <p>© 2024 OOSkills. Tous droits réservés.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text fallback
        plain_message = f"""
Bonjour {user.first_name or user.email.split('@')[0]},

Vous avez demandé la réinitialisation de votre mot de passe sur OOSkills.

Cliquez sur le lien ci-dessous pour créer un nouveau mot de passe:

{reset_url}

Ce lien expire dans 1 heure.

Si vous n'avez pas demandé la réinitialisation de votre mot de passe, ignorez simplement cet email.

© 2024 OOSkills. Tous droits réservés.
        """
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True
    except Exception as e:
        print(f"Error sending password reset email: {e}")
        return False


def verify_password_reset_token(token):
    """
    Verify password reset token.
    
    Args:
        token: Token string
        
    Returns:
        Tuple of (success: bool, user: User or None, error_message: str)
    """
    from .models import PasswordResetToken
    
    try:
        reset_token = PasswordResetToken.objects.select_related('user').get(
            token=token
        )
    except PasswordResetToken.DoesNotExist:
        return False, None, "Token invalide."
    
    if reset_token.is_used:
        return False, reset_token.user, "Ce lien a déjà été utilisé."
    
    if reset_token.is_expired:
        return False, reset_token.user, "Ce lien a expiré. Veuillez faire une nouvelle demande."
    
    return True, reset_token.user, "Token valide."
