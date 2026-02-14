"""
Supabase Storage backend for formation module.

Provides a Django Storage backend that uploads files to Supabase Storage,
so FileField / ImageField work seamlessly with Supabase.
"""

import uuid
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
from users.storage import get_supabase_client


class SupabaseAudioStorage(Storage):
    """
    Django Storage backend that stores files in the Supabase 'audios' bucket.

    Usage on a model field:
        audioUrl = models.FileField(
            upload_to=audio_upload_path,
            storage=SupabaseAudioStorage(),
        )
    """

    bucket_name = 'audios'

    def deconstruct(self):
        """Allow Django to serialize this storage in migrations."""
        return ('formation.storage.SupabaseAudioStorage', [], {})

    def _save(self, name, content):
        """Upload file to Supabase Storage and return the path."""
        supabase = get_supabase_client()

        file_content = content.read()

        # Guess content type
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        content_type_map = {
            'mp3': 'audio/mpeg',
            'wav': 'audio/wav',
            'ogg': 'audio/ogg',
            'aac': 'audio/aac',
            'm4a': 'audio/mp4',
            'webm': 'audio/webm',
        }
        content_type = content_type_map.get(ext, 'application/octet-stream')

        supabase.storage.from_(self.bucket_name).upload(
            path=name,
            file=file_content,
            file_options={
                'content-type': content_type,
                'upsert': 'true',
            },
        )

        return name

    def url(self, name):
        """Return the public URL for the file."""
        if not name:
            return ''
        # If already a full URL, return as-is
        if name.startswith('http'):
            return name
        supabase = get_supabase_client()
        return supabase.storage.from_(self.bucket_name).get_public_url(name)

    def exists(self, name):
        """Supabase uses upsert, so always return False to allow overwrite."""
        return False

    def delete(self, name):
        """Delete a file from Supabase Storage."""
        if not name or name.startswith('http'):
            return
        try:
            supabase = get_supabase_client()
            supabase.storage.from_(self.bucket_name).remove([name])
        except Exception:
            pass

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
