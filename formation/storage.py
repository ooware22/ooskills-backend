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
from urllib.parse import quote
from django.conf import settings
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
from users.storage import get_supabase_client

logger = logging.getLogger(__name__)

# Global semaphore to prevent TCP/Pool exhaustion when batch-uploading courses without triggering ThreadPoolExecutor statreloader bugs
import time
SUPABASE_UPLOAD_SEMAPHORE = threading.Semaphore(3)

# =============================================================================
# HELPERS
# =============================================================================

def _upload_to_supabase(bucket_name, path, file_content, content_type, retries=4):
    """Upload file bytes to Supabase Storage in a background thread."""
    supabase = get_supabase_client()
    for attempt in range(retries):
        try:
            supabase.storage.from_(bucket_name).upload(
                path=path,
                file=file_content,
                file_options={
                    'content-type': content_type,
                    'upsert': 'true',
                },
            )
            logger.info("Supabase upload OK  bucket=%s path=%s", bucket_name, path)
            return
        except Exception as e:
            if attempt < retries - 1:
                logger.warning("Supabase upload failed (attempt %d/%d) bucket=%s path=%s: %s", attempt+1, retries, bucket_name, path, e)
                # Exponential backoff with small base to relieve network congestion
                time.sleep(2 * (attempt + 1))
            else:
                logger.exception("Supabase upload FAILED completely after %d attempts! bucket=%s path=%s", retries, bucket_name, path)

def _upload_to_supabase_with_semaphore(bucket_name, path, file_content, content_type):
    """Wrapper to rate limit background threads."""
    with SUPABASE_UPLOAD_SEMAPHORE:
        _upload_to_supabase(bucket_name, path, file_content, content_type)

def _delete_from_supabase(bucket_name, name):
    """Delete a file from Supabase Storage in a background thread."""
    try:
        supabase = get_supabase_client()
        supabase.storage.from_(bucket_name).remove([name])
        logger.info("Supabase delete OK  bucket=%s path=%s", bucket_name, name)
    except Exception:
        logger.exception("Supabase delete FAILED  bucket=%s path=%s", bucket_name, name)

def _delete_course_storage_from_supabase(course_id_str, course_slug):
    """Deletes all storage files for a course across all buckets."""
    try:
        supabase = get_supabase_client()
        
        buckets_configs = [
            ('audios', course_id_str),
            ('materials', course_id_str),
            ('Diapositive', course_id_str),
            ('images', f"courses/{course_slug}")
        ]

        for bucket, folder_path in buckets_configs:
            try:
                res = supabase.storage.from_(bucket).list(folder_path)
                if res and isinstance(res, list):
                    files_to_delete = []
                    for item in res:
                        name = item.get('name')
                        # Sometimes empty folders use a placeholder or simply we get subdirs
                        if name and name not in ('.emptyFolderPlaceholder', ''):
                            files_to_delete.append(f"{folder_path}/{name}")
                    
                    if files_to_delete:
                        # Delete in chunks of 100 just in case there are too many
                        chunk_size = 100
                        for i in range(0, len(files_to_delete), chunk_size):
                            chunk = files_to_delete[i:i + chunk_size]
                            supabase.storage.from_(bucket).remove(chunk)
                        logger.info("Deleted %d files from bucket %s in folder %s", len(files_to_delete), bucket, folder_path)
            except Exception as e:
                logger.warning("Failed to clean up storage for bucket %s folder %s: %s", bucket, folder_path, e)
    except Exception as e:
        logger.error("Failed to initialize supabase client for course storage deletion: %s", e)

def delete_course_storage_async(course_id_str, course_slug):
    """Trigger background deletion of a course's storage."""
    threading.Thread(
        target=_delete_course_storage_from_supabase,
        args=(course_id_str, course_slug),
        daemon=True
    ).start()


CONTENT_TYPE_JPEG = 'image/jpeg'
CONTENT_TYPE_PNG = 'image/png'

AUDIO_CONTENT_TYPES = {
    'mp3': 'audio/mpeg',
    'wav': 'audio/wav',
    'ogg': 'audio/ogg',
    'aac': 'audio/aac',
    'm4a': 'audio/mp4',
    'webm': 'audio/webm',
}

IMAGE_CONTENT_TYPES = {
    'jpg': CONTENT_TYPE_JPEG,
    'jpeg': CONTENT_TYPE_JPEG,
    'png': CONTENT_TYPE_PNG,
    'gif': 'image/gif',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
    'avif': 'image/avif',
}


def _guess_content_type(name, type_map):
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return type_map.get(ext, 'application/octet-stream')


def _public_object_url(bucket_name, name):
    """Build Supabase public URL without creating SDK clients per field."""
    if not name:
        return ''
    if name.startswith('http'):
        return name

    base_url = (settings.SUPABASE_URL or '').rstrip('/')
    if not base_url:
        return name

    encoded_name = quote(name.lstrip('/'), safe='/')
    return f"{base_url}/storage/v1/object/public/{bucket_name}/{encoded_name}"


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

        threading.Thread(
            target=_upload_to_supabase_with_semaphore,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True
        ).start()

        return name

    def url(self, name):
        """Return the public URL for the file."""
        return _public_object_url(self.bucket_name, name)

    def exists(self, name):
        """Supabase uses upsert, so always return False to allow overwrite."""
        return False

    def delete(self, name):
        """Delete a file from Supabase Storage (async)."""
        if not name or name.startswith('http'):
            return
        threading.Thread(
            target=_delete_from_supabase,
            args=(self.bucket_name, name),
            daemon=True
        ).start()

    def size(self, name):
        return 0

    def listdir(self, path):
        return [], []


def audio_upload_path(instance, filename):
    """
    Generate upload path: <course_id>/<uuid>.<ext>

    This keeps audio files organised by course in the Supabase bucket.
    """
    # FinalQuiz has a direct `course` FK.
    # FinalQuizAudio goes through `final_quiz.course`.
    # Lesson goes through `module.section.course`.
    if hasattr(instance, 'course_id') and instance.course_id:
        course_id = str(instance.course_id)
    elif hasattr(instance, 'final_quiz_id') and instance.final_quiz_id:
        course_id = str(instance.final_quiz.course_id)
    elif hasattr(instance, 'module_id') and instance.module_id:
        course_id = str(instance.module.section.course_id)
    else:
        # Fallback: try legacy section path
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

        threading.Thread(
            target=_upload_to_supabase_with_semaphore,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True
        ).start()

        return name

    def url(self, name):
        """Return the public URL for the file."""
        return _public_object_url(self.bucket_name, name)

    def exists(self, name):
        """Supabase uses upsert, so always return False to allow overwrite."""
        return False

    def delete(self, name):
        """Delete a file from Supabase Storage (async)."""
        if not name or name.startswith('http'):
            return
        threading.Thread(
            target=_delete_from_supabase,
            args=(self.bucket_name, name),
            daemon=True
        ).start()

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
    'jpg': CONTENT_TYPE_JPEG,
    'jpeg': CONTENT_TYPE_JPEG,
    'png': CONTENT_TYPE_PNG,
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

        threading.Thread(
            target=_upload_to_supabase_with_semaphore,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True
        ).start()

        return name

    def url(self, name):
        return _public_object_url(self.bucket_name, name)

    def exists(self, name):
        return False

    def delete(self, name):
        if not name or name.startswith('http'):
            return
        threading.Thread(
            target=_delete_from_supabase,
            args=(self.bucket_name, name),
            daemon=True
        ).start()

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
    'jpg': CONTENT_TYPE_JPEG,
    'jpeg': CONTENT_TYPE_JPEG,
    'png': CONTENT_TYPE_PNG,
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

        threading.Thread(
            target=_upload_to_supabase_with_semaphore,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True
        ).start()

        return name

    def url(self, name):
        return _public_object_url(self.bucket_name, name)

    def exists(self, name):
        return False

    def delete(self, name):
        if not name or name.startswith('http'):
            return
        threading.Thread(
            target=_delete_from_supabase,
            args=(self.bucket_name, name),
            daemon=True
        ).start()

    def size(self, name):
        return 0

    def listdir(self, path):
        return [], []


def diapositive_upload_path(instance, filename):
    """
    Generate upload path: <course_id>/<uuid>.<ext>

    Keeps diapositive files grouped by course ID in the Supabase 'Diapositive' bucket.
    """
    # Lesson goes through module.section.course
    if hasattr(instance, 'module_id') and instance.module_id:
        course_id = str(instance.module.section.course_id)
    elif hasattr(instance, 'section_id') and instance.section_id:
        course_id = str(instance.section.course_id)
    else:
        course_id = str(instance.module.section.course_id)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'pdf'
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    return f"{course_id}/{unique_name}"
