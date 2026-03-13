"""
Supabase Storage backend for formation module.

Provides a Django Storage backend that uploads files to Supabase Storage,
so FileField / ImageField work seamlessly with Supabase.

Uploads are performed asynchronously in background threads so that API
responses return immediately without waiting for the Supabase upload.
"""

import logging
import uuid
import threading
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
from users.storage import get_supabase_client

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def _upload_to_supabase(bucket_name, path, file_content, content_type):
    """Upload file bytes to Supabase Storage in a background thread."""
    try:
        supabase = get_supabase_client()
        supabase.storage.from_(bucket_name).upload(
            path=path,
            file=file_content,
            file_options={
                'content-type': content_type,
                'upsert': 'true',
            },
        )
        logger.info("Supabase upload OK  bucket=%s path=%s", bucket_name, path)
    except Exception:
        logger.exception("Supabase upload FAILED  bucket=%s path=%s", bucket_name, path)


def _delete_from_supabase(bucket_name, name):
    """Delete a file from Supabase Storage in a background thread."""
    try:
        supabase = get_supabase_client()
        supabase.storage.from_(bucket_name).remove([name])
        logger.info("Supabase delete OK  bucket=%s path=%s", bucket_name, name)
    except Exception:
        logger.exception("Supabase delete FAILED  bucket=%s path=%s", bucket_name, name)


AUDIO_CONTENT_TYPES = {
    'mp3': 'audio/mpeg',
    'wav': 'audio/wav',
    'ogg': 'audio/ogg',
    'aac': 'audio/aac',
    'm4a': 'audio/mp4',
    'webm': 'audio/webm',
}

IMAGE_CONTENT_TYPES = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
    'avif': 'image/avif',
}


def _guess_content_type(name, type_map):
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return type_map.get(ext, 'application/octet-stream')


# =============================================================================
# AUDIO STORAGE
# =============================================================================

class SupabaseAudioStorage(Storage):
    """
    Django Storage backend that stores files in the Supabase 'audios' bucket.
    Uploads happen asynchronously so the API returns immediately.
    """

    bucket_name = 'audios'

    def deconstruct(self):
        """Allow Django to serialize this storage in migrations."""
        return ('formation.storage.SupabaseAudioStorage', [], {})

    def _save(self, name, content):
        """Read file bytes, fire off background upload, return path immediately."""
        file_content = content.read()
        content_type = _guess_content_type(name, AUDIO_CONTENT_TYPES)

        thread = threading.Thread(
            target=_upload_to_supabase,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True,
        )
        thread.start()

        return name

    def url(self, name):
        """Return the public URL for the file."""
        if not name:
            return ''
        if name.startswith('http'):
            return name
        supabase = get_supabase_client()
        return supabase.storage.from_(self.bucket_name).get_public_url(name)

    def exists(self, name):
        """Supabase uses upsert, so always return False to allow overwrite."""
        return False

    def delete(self, name):
        """Delete a file from Supabase Storage (async)."""
        if not name or name.startswith('http'):
            return
        thread = threading.Thread(
            target=_delete_from_supabase,
            args=(self.bucket_name, name),
            daemon=True,
        )
        thread.start()

    def size(self, name):
        return 0

    def listdir(self, path):
        return [], []


def audio_upload_path(instance, filename):
    """
    Generate upload path: <course_id>/<uuid>.<ext>

    This keeps audio files organised by course in the Supabase bucket.
    """
    course_id = str(instance.section.course_id)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp3'
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    return f"{course_id}/{unique_name}"


# =============================================================================
# IMAGE STORAGE
# =============================================================================

class SupabaseImageStorage(Storage):
    """
    Django Storage backend that stores files in the Supabase 'images' bucket.
    Uploads happen asynchronously so the API returns immediately.
    """

    bucket_name = 'images'

    def deconstruct(self):
        """Allow Django to serialize this storage in migrations."""
        return ('formation.storage.SupabaseImageStorage', [], {})

    def _save(self, name, content):
        """Read file bytes, fire off background upload, return path immediately."""
        file_content = content.read()
        content_type = _guess_content_type(name, IMAGE_CONTENT_TYPES)

        thread = threading.Thread(
            target=_upload_to_supabase,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True,
        )
        thread.start()

        return name

    def url(self, name):
        """Return the public URL for the file."""
        if not name:
            return ''
        if name.startswith('http'):
            return name
        supabase = get_supabase_client()
        return supabase.storage.from_(self.bucket_name).get_public_url(name)

    def exists(self, name):
        """Supabase uses upsert, so always return False to allow overwrite."""
        return False

    def delete(self, name):
        """Delete a file from Supabase Storage (async)."""
        if not name or name.startswith('http'):
            return
        thread = threading.Thread(
            target=_delete_from_supabase,
            args=(self.bucket_name, name),
            daemon=True,
        )
        thread.start()

    def size(self, name):
        return 0

    def listdir(self, path):
        return [], []


def course_image_upload_path(instance, filename):
    """
    Generate upload path: courses/<slug>/<uuid>.<ext>

    This keeps course images organised by course slug in the Supabase bucket.
    """
    slug = instance.slug or str(instance.id)[:8]
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    return f"courses/{slug}/{unique_name}"


# =============================================================================
# MATERIAL STORAGE
# =============================================================================

MATERIAL_CONTENT_TYPES = {
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'mp4': 'video/mp4',
    'zip': 'application/zip',
    'txt': 'text/plain',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
}


class SupabaseMaterialStorage(Storage):
    """
    Django Storage backend that stores files in the Supabase 'materials' bucket.
    Files are grouped by course_id: materials/<course_id>/<uuid>.<ext>
    """

    bucket_name = 'materials'

    def deconstruct(self):
        return ('formation.storage.SupabaseMaterialStorage', [], {})

    def _save(self, name, content):
        file_content = content.read()
        content_type = _guess_content_type(name, MATERIAL_CONTENT_TYPES)

        thread = threading.Thread(
            target=_upload_to_supabase,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True,
        )
        thread.start()

        return name

    def url(self, name):
        if not name:
            return ''
        if name.startswith('http'):
            return name
        supabase = get_supabase_client()
        return supabase.storage.from_(self.bucket_name).get_public_url(name)

    def exists(self, name):
        return False

    def delete(self, name):
        if not name or name.startswith('http'):
            return
        thread = threading.Thread(
            target=_delete_from_supabase,
            args=(self.bucket_name, name),
            daemon=True,
        )
        thread.start()

    def size(self, name):
        return 0

    def listdir(self, path):
        return [], []


def material_upload_path(instance, filename):
    """
    Generate upload path: <course_id>/<uuid>.<ext>

    Keeps materials grouped by course ID in the Supabase 'materials' bucket.
    """
    course_id = str(instance.course_id)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    return f"{course_id}/{unique_name}"


# =============================================================================
# DIAPOSITIVE STORAGE
# =============================================================================

DIAPOSITIVE_CONTENT_TYPES = {
    'pdf': 'application/pdf',
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
    'mp4': 'video/mp4',
}


class SupabaseDiapositiveStorage(Storage):
    """
    Django Storage backend that stores files in the Supabase 'Diapositive' bucket.
    Files are grouped by course_id: <course_id>/<uuid>.<ext>
    """

    bucket_name = 'Diapositive'

    def deconstruct(self):
        return ('formation.storage.SupabaseDiapositiveStorage', [], {})

    def _save(self, name, content):
        file_content = content.read()
        content_type = _guess_content_type(name, DIAPOSITIVE_CONTENT_TYPES)

        thread = threading.Thread(
            target=_upload_to_supabase,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True,
        )
        thread.start()

        return name

    def url(self, name):
        if not name:
            return ''
        if name.startswith('http'):
            return name
        supabase = get_supabase_client()
        return supabase.storage.from_(self.bucket_name).get_public_url(name)

    def exists(self, name):
        return False

    def delete(self, name):
        if not name or name.startswith('http'):
            return
        thread = threading.Thread(
            target=_delete_from_supabase,
            args=(self.bucket_name, name),
            daemon=True,
        )
        thread.start()

    def size(self, name):
        return 0

    def listdir(self, path):
        return [], []


def diapositive_upload_path(instance, filename):
    """
    Generate upload path: <course_id>/<uuid>.<ext>

    Keeps diapositive files grouped by course ID in the Supabase 'Diapositive' bucket.
    """
    course_id = str(instance.section.course_id)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'pdf'
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    return f"{course_id}/{unique_name}"
