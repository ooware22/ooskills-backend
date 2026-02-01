"""
Supabase Authentication Backend for Django

This module provides:
1. JWT Authentication for Supabase Auth tokens
2. User sync between Supabase Auth and Django User model
3. Custom authentication backend for Django
"""

import jwt
from jwt import PyJWKClient
from django.conf import settings
from rest_framework import authentication, exceptions
from users.models import User


# =============================================================================
# SUPABASE JWT AUTHENTICATION
# =============================================================================

class SupabaseJWTAuthentication(authentication.BaseAuthentication):
    """
    Custom authentication class for Supabase Auth JWT tokens.
    
    Validates the JWT token from Supabase and syncs/creates the user
    in Django's database.
    
    Usage in settings.py:
        REST_FRAMEWORK = {
            'DEFAULT_AUTHENTICATION_CLASSES': [
                'users.authentication.SupabaseJWTAuthentication',
                ...
            ],
        }
    
    Expected header:
        Authorization: Bearer <supabase_jwt_token>
    """
    
    keyword = 'Bearer'
    
    def authenticate(self, request):
        """
        Authenticate the request and return a tuple of (user, token).
        """
        auth_header = authentication.get_authorization_header(request)
        
        if not auth_header:
            return None
        
        try:
            auth_parts = auth_header.decode('utf-8').split()
        except UnicodeDecodeError:
            raise exceptions.AuthenticationFailed('Invalid token header encoding.')
        
        if len(auth_parts) == 0:
            return None
        
        if auth_parts[0].lower() != self.keyword.lower():
            return None
        
        if len(auth_parts) == 1:
            raise exceptions.AuthenticationFailed('Invalid token header. No credentials provided.')
        
        if len(auth_parts) > 2:
            raise exceptions.AuthenticationFailed('Invalid token header. Token should not contain spaces.')
        
        token = auth_parts[1]
        return self.authenticate_token(token)
    
    def authenticate_token(self, token):
        """
        Validate the Supabase JWT token and return user.
        """
        try:
            # Decode token with Supabase JWT secret
            payload = self.decode_token(token)
            
            # Extract user info from token
            supabase_user_id = payload.get('sub')
            email = payload.get('email')
            
            if not supabase_user_id:
                raise exceptions.AuthenticationFailed('Invalid token: missing user ID.')
            
            # Get or create Django user
            user = self.get_or_create_user(supabase_user_id, email, payload)
            
            return (user, token)
            
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed('Token has expired.')
        except jwt.InvalidTokenError as e:
            raise exceptions.AuthenticationFailed(f'Invalid token: {str(e)}')
    
    def decode_token(self, token):
        """
        Decode and verify the Supabase JWT token.
        """
        supabase_jwt_secret = getattr(settings, 'SUPABASE_JWT_SECRET', None)
        
        if not supabase_jwt_secret:
            # Try to get from environment
            import os
            supabase_jwt_secret = os.environ.get('SUPABASE_JWT_SECRET')
        
        if not supabase_jwt_secret:
            raise exceptions.AuthenticationFailed('Supabase JWT secret not configured.')
        
        try:
            # Decode with HS256 (Supabase default)
            payload = jwt.decode(
                token,
                supabase_jwt_secret,
                algorithms=['HS256'],
                audience='authenticated',
            )
            return payload
        except jwt.InvalidAudienceError:
            # Try without audience check for service tokens
            payload = jwt.decode(
                token,
                supabase_jwt_secret,
                algorithms=['HS256'],
            )
            return payload
    
    def get_or_create_user(self, supabase_user_id, email, payload):
        """
        Get or create a Django user from Supabase token payload.
        """
        user_metadata = payload.get('user_metadata', {})
        app_metadata = payload.get('app_metadata', {})
        
        supabase_data = {
            'id': supabase_user_id,
            'email': email,
            'user_metadata': user_metadata,
            'app_metadata': app_metadata,
        }
        
        user, created = User.objects.get_or_create_from_supabase(supabase_data)
        
        # Update last login
        from django.utils import timezone
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
        
        return user
    
    def authenticate_header(self, request):
        """
        Return string to be used as the value of the WWW-Authenticate header.
        """
        return self.keyword


# =============================================================================
# SUPABASE AUTHENTICATION BACKEND (for Django auth)
# =============================================================================

class SupabaseAuthBackend:
    """
    Django authentication backend for Supabase Auth users.
    
    Allows users to authenticate with their Supabase credentials
    and syncs the user to Django's User model.
    
    Add to settings.py:
        AUTHENTICATION_BACKENDS = [
            'users.authentication.SupabaseAuthBackend',
            'django.contrib.auth.backends.ModelBackend',
        ]
    """
    
    def authenticate(self, request, supabase_id=None, email=None, **kwargs):
        """
        Authenticate user by Supabase ID or email.
        """
        if supabase_id:
            try:
                return User.objects.get(supabase_id=supabase_id)
            except User.DoesNotExist:
                return None
        
        if email:
            try:
                return User.objects.get(email=email)
            except User.DoesNotExist:
                return None
        
        return None
    
    def get_user(self, user_id):
        """
        Get user by primary key (UUID).
        """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def verify_supabase_token(token):
    """
    Standalone function to verify a Supabase JWT token.
    
    Returns:
        dict: Decoded token payload if valid
        None: If token is invalid
    """
    try:
        auth = SupabaseJWTAuthentication()
        payload = auth.decode_token(token)
        return payload
    except Exception:
        return None


def get_user_from_supabase_token(token):
    """
    Get or create a Django user from a Supabase JWT token.
    
    Returns:
        User: Django user object
        None: If token is invalid
    """
    try:
        auth = SupabaseJWTAuthentication()
        user, _ = auth.authenticate_token(token)
        return user
    except Exception:
        return None
