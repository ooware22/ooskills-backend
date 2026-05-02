"""
Storage Utility for OOSkills Platform

Supabase Auth helpers (create/delete auth users) remain here.
File storage (avatars) now uses Cloudflare R2 via boto3.
"""

import uuid
from django.conf import settings
from supabase import create_client, Client
import boto3
from botocore.config import Config




# ── Suppress "Storage endpoint URL should have a trailing slash" spam ──
# The storage3 SDK prints this on every storage.from_() call (line 20 of
# storage3/_sync/bucket.py).  We monkey-patch __init__ to silently fix
# the URL without printing.
try:
    from storage3._sync.bucket import SyncStorageBucketAPI as _SyncBucket
    from storage3._async.bucket import AsyncStorageBucketAPI as _AsyncBucket
    from yarl import URL as _URL
    from httpx import Client as _Client, Headers as _Headers

    def _quiet_sync_init(self, session: _Client, url: str, headers: _Headers) -> None:
        if url and url[-1] != "/":
            url += "/"
        self._base_url = _URL(url)
        self._client = session
        self._headers = headers

    _SyncBucket.__init__ = _quiet_sync_init  # type: ignore[assignment]

    # Same for async variant
    def _quiet_async_init(self, session, url: str, headers) -> None:
        if url and url[-1] != "/":
            url += "/"
        self._base_url = _URL(url)
        self._client = session
        self._headers = headers

    _AsyncBucket.__init__ = _quiet_async_init  # type: ignore[assignment]
except Exception:
    pass  # If the patch fails, just let the original print happen


def get_supabase_client() -> Client:
    """Create a Supabase client with service role key (used for Auth only)."""
    url = settings.SUPABASE_URL
    if not url.endswith('/'):
        url = url + '/'
    return create_client(url, settings.SUPABASE_SERVICE_ROLE_KEY)


def _get_r2_client():
    """Return a boto3 S3 client configured for Cloudflare R2."""
    return boto3.client(
        's3',
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version='s3v4'),
        region_name='auto',
    )


def create_supabase_auth_user(email: str, password: str = None, user_metadata: dict = None) -> dict:
    """
    Create a user in Supabase Auth.
    
    Args:
        email: User's email address
        password: Optional password (if not provided, a random one is generated)
        user_metadata: Optional metadata (first_name, last_name, etc.)
        
    Returns:
        Dict with 'id' (supabase_id) and 'email'
        
    Raises:
        Exception: If user creation fails
    """
    import secrets
    import string
    
    supabase = get_supabase_client()
    
    # Generate a random password if none provided
    if not password:
        alphabet = string.ascii_letters + string.digits + string.punctuation
        password = secrets.token_urlsafe(16)
    
    # Build user data
    user_data = {
        'email': email,
        'password': password,
        'email_confirm': True,  # Auto-confirm email for admin-created users
    }
    
    if user_metadata:
        user_data['user_metadata'] = user_metadata
    
    # Create user in Supabase Auth using admin API
    response = supabase.auth.admin.create_user(user_data)
    
    return {
        'id': response.user.id,
        'email': response.user.email
    }


def delete_supabase_auth_user(supabase_id: str) -> bool:
    """
    Delete a user from Supabase Auth.
    
    Args:
        supabase_id: User's Supabase Auth UUID
        
    Returns:
        True if deleted successfully
    """
    try:
        supabase = get_supabase_client()
        supabase.auth.admin.delete_user(supabase_id)
        return True
    except Exception:
        return False


def upload_avatar(file, user_id: str) -> str:
    """
    Upload user avatar to Cloudflare R2 'avatars' bucket.

    Args:
        file: Uploaded file object (from request.FILES)
        user_id: User's UUID as string

    Returns:
        Public URL of the uploaded file

    Raises:
        Exception: If upload fails
    """
    file_extension = file.name.split('.')[-1].lower()
    object_key = f"avatars/{user_id}.{file_extension}"

    file_content = file.read()

    content_type_map = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'webp': 'image/webp',
        'gif': 'image/gif',
    }
    content_type = content_type_map.get(file_extension, 'image/jpeg')

    client = _get_r2_client()
    client.put_object(
        Bucket='avatars',
        Key=object_key,
        Body=file_content,
        ContentType=content_type,
    )

    # Build public URL from R2_PUBLIC_URLS setting
    base_url = (settings.R2_PUBLIC_URLS.get('avatars') or '').rstrip('/')
    if base_url:
        return f"{base_url}/{object_key}"
    return object_key


def delete_avatar(file_url: str) -> bool:
    """
    Delete avatar from Cloudflare R2.

    Args:
        file_url: Public URL or object key of the file to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    if not file_url:
        return False

    try:
        client = _get_r2_client()

        # Extract the object key from a full URL or use as-is if already a key
        base_url = (settings.R2_PUBLIC_URLS.get('avatars') or '').rstrip('/')
        if base_url and file_url.startswith(base_url):
            object_key = file_url[len(base_url):].lstrip('/')
        elif file_url.startswith('http'):
            # Fallback: key is the path after the bucket name in the URL
            object_key = file_url.split('/avatars/', 1)[-1]
            if '/' not in object_key:
                object_key = f"avatars/{object_key}"
        else:
            object_key = file_url

        client.delete_object(Bucket='avatars', Key=object_key)
        return True
    except Exception:
        return False


def validate_image_file(file) -> tuple[bool, str]:
    """
    Validate uploaded image file.
    
    Args:
        file: Uploaded file object
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check file size (max 5MB)
    max_size = 5 * 1024 * 1024  # 5MB
    if file.size > max_size:
        return False, "La taille du fichier ne doit pas dépasser 5 Mo."
    
    # Check file extension
    allowed_extensions = ['jpg', 'jpeg', 'png', 'webp', 'gif']
    file_extension = file.name.split('.')[-1].lower()
    if file_extension not in allowed_extensions:
        return False, f"Format non supporté. Formats acceptés: {', '.join(allowed_extensions)}"
    
    return True, ""
