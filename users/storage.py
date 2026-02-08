"""
Supabase Storage Utility for OOSkills Platform

Provides functions for uploading and managing files in Supabase Storage.
"""

import uuid
from django.conf import settings
from supabase import create_client, Client


def get_supabase_client() -> Client:
    """Get Supabase client with service role key for storage operations."""
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY
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
    Upload user avatar to Supabase Storage.
    
    Args:
        file: Uploaded file object (from request.FILES)
        user_id: User's UUID as string
        
    Returns:
        Public URL of the uploaded file
        
    Raises:
        Exception: If upload fails
    """
    supabase = get_supabase_client()
    
    # Store in avatars/ folder, one file per user (overwritten on update)
    file_extension = file.name.split('.')[-1].lower()
    filename = f"avatars/{user_id}.{file_extension}"
    
    # Read file content
    file_content = file.read()
    
    # Determine content type
    content_type_map = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'webp': 'image/webp',
        'gif': 'image/gif',
    }
    content_type = content_type_map.get(file_extension, 'image/jpeg')
    
    # Upload to Supabase Storage
    response = supabase.storage.from_('avatars').upload(
        path=filename,
        file=file_content,
        file_options={
            'content-type': content_type,
            'upsert': 'true'
        }
    )
    
    # Get public URL
    public_url = supabase.storage.from_('avatars').get_public_url(filename)
    
    return public_url


def delete_avatar(file_url: str) -> bool:
    """
    Delete avatar from Supabase Storage.
    
    Args:
        file_url: Public URL of the file to delete
        
    Returns:
        True if deleted successfully, False otherwise
    """
    if not file_url or 'supabase' not in file_url:
        return False
    
    try:
        supabase = get_supabase_client()
        
        # Extract file path from URL
        # URL format: https://<project>.supabase.co/storage/v1/object/public/avatars/<path>
        if '/avatars/' in file_url:
            file_path = file_url.split('/avatars/')[-1]
            supabase.storage.from_('avatars').remove([file_path])
            return True
    except Exception:
        pass
    
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
