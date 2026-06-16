"""
Cloudflare R2 Storage backend for formation module.

Provides a Django Storage backend that uploads files to Cloudflare R2 (S3-compatible),
so FileField / ImageField work seamlessly with R2.

Uploads are performed asynchronously in background threads so that API
responses return immediately without waiting for the R2 upload.
"""

import io
import logging
import uuid
import time
import threading
from urllib.parse import quote
from django.conf import settings
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

# Global semaphore — limit concurrent uploads to avoid overwhelming R2.
R2_UPLOAD_SEMAPHORE = threading.Semaphore(8)

# Thread-local storage for reusing boto3 clients within a thread.
_thread_local = threading.local()

# Bucket used for temporary uploads (ZIP imports, etc.)
# Uses existing 'materials' bucket with a key prefix since the R2 token
# may not have CreateBucket permissions for a separate bucket.
R2_TEMP_BUCKET = 'materials'
R2_TEMP_PREFIX = 'temp-uploads/'


def generate_presigned_upload_url(object_key, content_type='application/zip', expires_in=3600):
    """
    Generate a presigned PUT URL for direct browser-to-R2 upload.

    This bypasses Cloudflare's proxy size limit (100 MB on free plan)
    because the browser uploads directly to the R2 endpoint.

    Returns a dict with 'upload_url', 'object_key', and 'expires_in'.
    """
    client = _get_r2_client()
    # NOTE: Do NOT include ContentType in Params — different browsers report
    # different MIME types for .zip files (application/zip, application/x-zip-compressed,
    # application/octet-stream) which causes SignatureDoesNotMatch errors.
    url = client.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': R2_TEMP_BUCKET,
            'Key': object_key,
        },
        ExpiresIn=expires_in,
    )
    return {
        'upload_url': url,
        'object_key': object_key,
        'bucket': R2_TEMP_BUCKET,
        'expires_in': expires_in,
    }


def download_r2_object_to_file(bucket, key, dest_path):
    """
    Download an object from R2 to a local file path.

    Used after the browser uploads a ZIP directly to R2 —
    the backend downloads it locally for processing.
    """
    client = _get_r2_client()
    client.download_file(bucket, key, dest_path)
    logger.info('R2 download OK  bucket=%s key=%s → %s', bucket, key, dest_path)


def delete_r2_object(bucket, key):
    """Delete a single object from R2 (cleanup after processing)."""
    try:
        client = _get_r2_client()
        client.delete_object(Bucket=bucket, Key=key)
        logger.info('R2 cleanup OK  bucket=%s key=%s', bucket, key)
    except Exception:
        logger.exception('R2 cleanup FAILED  bucket=%s key=%s', bucket, key)


def _get_r2_client():
    """Return a boto3 S3 client configured for Cloudflare R2, cached per-thread."""
    client = getattr(_thread_local, 'r2_client', None)
    if client is None:
        client = boto3.client(
            's3',
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=Config(signature_version='s3v4'),
            region_name='auto',
        )
        _thread_local.r2_client = client
    return client


# Maximum image dimension (pixels) before we downscale during import.
IMPORT_IMAGE_MAX_DIM = 1920
# JPEG/WebP quality for compressed slides.
IMPORT_IMAGE_QUALITY = 82


def compress_image_bytes(file_bytes, filename, max_dim=IMPORT_IMAGE_MAX_DIM, quality=IMPORT_IMAGE_QUALITY):
    """
    Compress an image if it is larger than *max_dim* pixels on any side.

    Returns (compressed_bytes, new_filename, content_type).
    Falls back to the original bytes if Pillow is not available or the
    image cannot be decoded.
    """
    try:
        from PIL import Image
    except ImportError:
        # Pillow not installed — return as-is
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        ct = IMAGE_CONTENT_TYPES.get(ext, 'application/octet-stream')
        return file_bytes, filename, ct

    try:
        img = Image.open(io.BytesIO(file_bytes))
    except Exception:
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        ct = IMAGE_CONTENT_TYPES.get(ext, 'application/octet-stream')
        return file_bytes, filename, ct

    w, h = img.size
    resized = False
    if max(w, h) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        resized = True

    # Convert to RGB if necessary (handles RGBA PNGs)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    # Save as WebP for best size/quality ratio
    buf = io.BytesIO()
    img.save(buf, format='WEBP', quality=quality, method=4)
    compressed = buf.getvalue()

    # Only use compressed version if it is actually smaller
    if len(compressed) < len(file_bytes) or resized:
        new_name = filename.rsplit('.', 1)[0] + '.webp'
        logger.info(
            "Image compressed %s → %s  (%d KB → %d KB)",
            filename, new_name,
            len(file_bytes) // 1024, len(compressed) // 1024,
        )
        return compressed, new_name, 'image/webp'

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    ct = IMAGE_CONTENT_TYPES.get(ext, 'application/octet-stream')
    return file_bytes, filename, ct

# =============================================================================
# HELPERS
# =============================================================================

def _upload_to_r2(bucket_name, path, file_content, content_type, retries=4):
    """Upload file bytes to Cloudflare R2, reusing a per-thread boto3 client."""
    client = _get_r2_client()
    for attempt in range(retries):
        try:
            client.put_object(
                Bucket=bucket_name,
                Key=path,
                Body=file_content,
                ContentType=content_type,
            )
            logger.info('R2 upload OK  bucket=%s path=%s (%d KB)', bucket_name, path, len(file_content) // 1024)
            return
        except Exception as e:
            if attempt < retries - 1:
                logger.warning('R2 upload failed (attempt %d/%d) bucket=%s path=%s: %s', attempt + 1, retries, bucket_name, path, e)
                time.sleep(2 * (attempt + 1))
            else:
                logger.exception('R2 upload FAILED completely after %d attempts! bucket=%s path=%s', retries, bucket_name, path)


def _upload_to_r2_with_semaphore(bucket_name, path, file_content, content_type):
    """Wrapper to rate-limit background R2 upload threads."""
    with R2_UPLOAD_SEMAPHORE:
        _upload_to_r2(bucket_name, path, file_content, content_type)


def _delete_from_r2(bucket_name, name):
    """Delete a file from Cloudflare R2 in a background thread."""
    try:
        client = _get_r2_client()
        client.delete_object(Bucket=bucket_name, Key=name)
        logger.info('R2 delete OK  bucket=%s path=%s', bucket_name, name)
    except Exception:
        logger.exception('R2 delete FAILED  bucket=%s path=%s', bucket_name, name)


def _delete_course_storage_from_r2(course_id_str, course_slug):
    """Delete all R2 objects for a course across all relevant buckets."""
    try:
        client = _get_r2_client()

        buckets_prefixes = [
            ('audios',      course_id_str),
            ('materials',   course_id_str),
            ('diapositive', course_id_str),
            ('images',      f'courses/{course_slug}'),
        ]

        for bucket, prefix in buckets_prefixes:
            try:
                paginator = client.get_paginator('list_objects_v2')
                keys_to_delete = []
                for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                    for obj in page.get('Contents', []):
                        keys_to_delete.append({'Key': obj['Key']})

                if keys_to_delete:
                    # R2 supports up to 1000 keys per delete_objects call
                    chunk_size = 1000
                    for i in range(0, len(keys_to_delete), chunk_size):
                        client.delete_objects(
                            Bucket=bucket,
                            Delete={'Objects': keys_to_delete[i:i + chunk_size]},
                        )
                    logger.info('Deleted %d objects from R2 bucket=%s prefix=%s', len(keys_to_delete), bucket, prefix)
            except Exception as e:
                logger.warning('Failed to clean R2 bucket=%s prefix=%s: %s', bucket, prefix, e)
    except Exception as e:
        logger.error('R2 course storage deletion failed: %s', e)


def delete_course_storage_async(course_id_str, course_slug):
    """Trigger background deletion of a course's R2 storage."""
    threading.Thread(
        target=_delete_course_storage_from_r2,
        args=(course_id_str, course_slug),
        daemon=True,
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
    """Build the public URL for an R2 object using the per-bucket base URL from settings."""
    if not name:
        return ''
    if name.startswith('http'):
        return name

    base_url = (settings.R2_PUBLIC_URLS.get(bucket_name) or '').rstrip('/')
    if not base_url:
        return name

    encoded_name = quote(name.lstrip('/'), safe='/')
    return f"{base_url}/{encoded_name}"


# =============================================================================
# AUDIO STORAGE
# =============================================================================

class SupabaseAudioStorage(Storage):
    """
    Django Storage backend that stores audio files in Cloudflare R2 'audios' bucket.
    Uploads happen asynchronously so the API returns immediately.
    """

    bucket_name = 'audios'

    def deconstruct(self):
        return ('formation.storage.SupabaseAudioStorage', [], {})

    def _save(self, name, content):
        file_content = content.read()
        content_type = _guess_content_type(name, AUDIO_CONTENT_TYPES)
        threading.Thread(
            target=_upload_to_r2_with_semaphore,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True,
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
            target=_delete_from_r2,
            args=(self.bucket_name, name),
            daemon=True,
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
    Django Storage backend that stores images in Cloudflare R2 'images' bucket.
    Uploads happen asynchronously so the API returns immediately.
    """

    bucket_name = 'images'

    def deconstruct(self):
        return ('formation.storage.SupabaseImageStorage', [], {})

    def _save(self, name, content):
        """Read file bytes, fire off background upload, return path immediately."""
        file_content = content.read()
        content_type = _guess_content_type(name, IMAGE_CONTENT_TYPES)

        threading.Thread(
            target=_upload_to_r2_with_semaphore,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True,
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
            target=_delete_from_r2,
            args=(self.bucket_name, name),
            daemon=True,
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
    Django Storage backend that stores files in Cloudflare R2 'materials' bucket.
    Files are grouped by course_id: materials/<course_id>/<uuid>.<ext>
    """

    bucket_name = 'materials'

    def deconstruct(self):
        return ('formation.storage.SupabaseMaterialStorage', [], {})

    def _save(self, name, content):
        file_content = content.read()
        content_type = _guess_content_type(name, MATERIAL_CONTENT_TYPES)

        threading.Thread(
            target=_upload_to_r2_with_semaphore,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True,
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
            target=_delete_from_r2,
            args=(self.bucket_name, name),
            daemon=True,
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
    Django Storage backend that stores files in Cloudflare R2 'diapositive' bucket.
    Files are grouped by course_id: <course_id>/<uuid>.<ext>
    """

    bucket_name = 'diapositive'

    def deconstruct(self):
        return ('formation.storage.SupabaseDiapositiveStorage', [], {})

    def _save(self, name, content):
        file_content = content.read()
        content_type = _guess_content_type(name, DIAPOSITIVE_CONTENT_TYPES)

        threading.Thread(
            target=_upload_to_r2_with_semaphore,
            args=(self.bucket_name, name, file_content, content_type),
            daemon=True,
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
            target=_delete_from_r2,
            args=(self.bucket_name, name),
            daemon=True,
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
