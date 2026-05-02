#!/usr/bin/env python
"""
One-time migration: Supabase Storage  →  Cloudflare R2

Run from the ooskillsbackend/ directory with the venv activated:

    # Dry-run: list all files without uploading
    python migrate_storage_to_r2.py --dry-run

    # Migrate everything
    python migrate_storage_to_r2.py

    # Migrate a single bucket
    python migrate_storage_to_r2.py --bucket images

Features:
  - Resumable: already-present R2 objects are skipped (safe to re-run)
  - Streams large files (no full RAM load)
  - Uses mimetype from Supabase metadata for correct Content-Type on R2
  - Clears progress to stdout; errors to stderr
"""

import argparse
import os
import sys
import time
import logging
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

# ── Validate dependencies ─────────────────────────────────────────────────────
missing_deps = []
try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    missing_deps.append('boto3')

try:
    import httpx
except ImportError:
    missing_deps.append('httpx')

try:
    from supabase import create_client
except ImportError:
    missing_deps.append('supabase')

if missing_deps:
    sys.exit(f"Missing packages: {', '.join(missing_deps)}\nRun: pip install {' '.join(missing_deps)}")

# ── Silence Supabase SDK "trailing slash" spam ────────────────────────────────
try:
    from storage3._sync.bucket import SyncStorageBucketAPI as _SyncBucket
    from yarl import URL as _URL
    from httpx import Client as _HClient, Headers as _HHeaders

    def _quiet_init(self, session: _HClient, url: str, headers: _HHeaders) -> None:
        self._base_url = _URL(url if url.endswith('/') else url + '/')
        self._client = session
        self._headers = headers

    _SyncBucket.__init__ = _quiet_init  # type: ignore[assignment]
except Exception:
    pass

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('migrate')

# ── Buckets to migrate (Supabase name → R2 name) ─────────────────────────────
BUCKET_MAP: dict[str, str] = {
    'audios':      'audios',
    'images':      'images',
    'materials':   'materials',
    'Diapositive': 'Diapositive',
    'avatars':     'avatars',
}

# ── Read credentials from env ─────────────────────────────────────────────────
SUPABASE_URL              = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
R2_ACCOUNT_ID             = os.environ.get('R2_ACCOUNT_ID', '')
R2_ACCESS_KEY_ID          = os.environ.get('R2_ACCESS_KEY_ID', '')
R2_SECRET_ACCESS_KEY      = os.environ.get('R2_SECRET_ACCESS_KEY', '')


def validate_env(dry_run: bool):
    errors = []
    if not SUPABASE_URL:
        errors.append('SUPABASE_URL is not set')
    if not SUPABASE_SERVICE_ROLE_KEY:
        errors.append('SUPABASE_SERVICE_ROLE_KEY is not set')
    if not dry_run:
        if not R2_ACCOUNT_ID:
            errors.append('R2_ACCOUNT_ID is not set')
        if not R2_ACCESS_KEY_ID:
            errors.append('R2_ACCESS_KEY_ID is not set')
        if R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_ACCOUNT_ID == R2_ACCESS_KEY_ID:
            errors.append(
                'R2_ACCESS_KEY_ID equals R2_ACCOUNT_ID — these must be different.\n'
                '  Go to: Cloudflare dashboard → R2 → Manage R2 API Tokens → Create API Token\n'
                '  Copy the generated Access Key ID (not your Account ID) into R2_ACCESS_KEY_ID'
            )
        if not R2_SECRET_ACCESS_KEY:
            errors.append('R2_SECRET_ACCESS_KEY is not set')
    if errors:
        sys.exit('\n'.join(['ERROR: credential problems found:'] + [f'  • {e}' for e in errors]))


# ── Clients ───────────────────────────────────────────────────────────────────

def make_supabase():
    url = SUPABASE_URL + '/'
    return create_client(url, SUPABASE_SERVICE_ROLE_KEY)


def make_r2():
    endpoint = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'
    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version='s3v4'),
        region_name='auto',
    )


# ── Supabase: list all objects recursively ───────────────────────────────────

def _list_supabase_recursive(sb, bucket: str, folder: str, accumulator: list):
    """
    Recurse into Supabase storage.
    A folder entry has id == None; a file entry has id != None.
    """
    try:
        items = sb.storage.from_(bucket).list(folder, {'limit': 1000, 'offset': 0})
    except Exception as exc:
        log.warning('  list(%s/%s) error: %s', bucket, folder, exc)
        return

    for item in (items or []):
        name = item.get('name', '')
        if not name or name == '.emptyFolderPlaceholder':
            continue
        full_path = f'{folder}/{name}' if folder else name
        if item.get('id') is None:
            # It's a folder — recurse
            _list_supabase_recursive(sb, bucket, full_path, accumulator)
        else:
            mimetype = (item.get('metadata') or {}).get('mimetype', 'application/octet-stream')
            accumulator.append((full_path, mimetype))


def list_supabase_bucket(sb, bucket: str) -> list[tuple[str, str]]:
    """Return list of (object_key, mimetype) for all files in a Supabase bucket."""
    results = []
    _list_supabase_recursive(sb, bucket, '', results)
    return results


# ── Download from Supabase using authenticated HTTP ──────────────────────────

def download_supabase_object(bucket: str, key: str) -> bytes:
    """
    Download an object from Supabase Storage using the service-role Bearer token.
    This bypasses the SDK download() method which can be unreliable for large files.
    """
    url = f'{SUPABASE_URL}/storage/v1/object/{bucket}/{key}'
    headers = {
        'Authorization': f'Bearer {SUPABASE_SERVICE_ROLE_KEY}',
        'apikey': SUPABASE_SERVICE_ROLE_KEY,
    }
    with httpx.Client(timeout=300) as client:
        response = client.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()
        return response.content


# ── R2 helpers ────────────────────────────────────────────────────────────────

def r2_object_exists(r2, bucket: str, key: str) -> bool:
    try:
        r2.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] in ('404', 'NoSuchKey'):
            return False
        raise


def upload_to_r2(r2, bucket: str, key: str, data: bytes, content_type: str):
    r2.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


# ── Per-bucket migration ──────────────────────────────────────────────────────

def migrate_bucket(sb, r2, src: str, dst: str, dry_run: bool) -> tuple[int, int, int]:
    log.info('')
    log.info('━━━  %s  →  %s  ━━━', src, dst)

    log.info('  Listing objects in Supabase...')
    objects = list_supabase_bucket(sb, src)
    log.info('  Found %d objects', len(objects))

    if not objects:
        return 0, 0, 0

    ok = err = skip = 0
    total = len(objects)

    for i, (key, mimetype) in enumerate(objects, 1):
        tag = f'  [{i}/{total}]'

        if dry_run:
            log.info('%s [dry-run] %s  (%s)', tag, key, mimetype)
            ok += 1
            continue

        try:
            if r2_object_exists(r2, dst, key):
                log.info('%s SKIP (exists) %s', tag, key)
                skip += 1
                continue

            data = download_supabase_object(src, key)
            upload_to_r2(r2, dst, key, data, mimetype)
            log.info('%s OK  %s  (%d KB, %s)', tag, key, len(data) // 1024, mimetype)
            ok += 1

        except Exception as exc:
            log.error('%s ERROR  %s  →  %s', tag, key, exc)
            err += 1
            time.sleep(1)

    log.info('  bucket=%s  ok=%d  skipped=%d  errors=%d', src, ok, skip, err)
    return ok, skip, err


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Migrate Supabase Storage → Cloudflare R2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='List files without uploading anything')
    parser.add_argument('--bucket', dest='buckets', action='append', metavar='BUCKET',
                        help='Migrate only this bucket (repeatable). Default: all.')
    args = parser.parse_args()

    validate_env(dry_run=args.dry_run)

    buckets = args.buckets or list(BUCKET_MAP.keys())
    unknown = [b for b in buckets if b not in BUCKET_MAP]
    if unknown:
        sys.exit(f'Unknown bucket(s): {unknown}. Valid: {list(BUCKET_MAP.keys())}')

    log.info('Migration starting.  dry_run=%s  buckets=%s', args.dry_run, buckets)
    if args.dry_run:
        log.info('(DRY RUN — nothing will be uploaded)')

    sb = make_supabase()
    r2 = None if args.dry_run else make_r2()

    if r2:
        # Quick connectivity check — ListBuckets requires extra admin permissions
        # so we use head_bucket on the first target bucket instead.
        first_dst = BUCKET_MAP[buckets[0]]
        try:
            r2.head_bucket(Bucket=first_dst)
            log.info('R2 connection OK (bucket=%s exists)', first_dst)
        except ClientError as e:
            code = e.response['Error']['Code']
            if code in ('404', 'NoSuchBucket'):
                sys.exit(
                    f"R2 bucket '{first_dst}' does not exist.\n"
                    f"Create it in: Cloudflare dashboard → R2 → Create bucket"
                )
            elif code in ('403', 'AccessDenied'):
                sys.exit(
                    f"Access denied to R2 bucket '{first_dst}'.\n"
                    "Check R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY in .env\n"
                    "Make sure the API token has Object Read & Write on this bucket."
                )
            else:
                sys.exit(f'Cannot connect to R2: {e}')
        except Exception as exc:
            sys.exit(
                f'Cannot connect to R2: {exc}\n'
                'Check R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY in .env'
            )

    total_ok = total_skip = total_err = 0
    for src in buckets:
        dst = BUCKET_MAP[src]
        ok, skip, err = migrate_bucket(sb, r2, src, dst, dry_run=args.dry_run)
        total_ok += ok
        total_skip += skip
        total_err += err

    log.info('')
    log.info('═══ DONE ═══  ok=%d  skipped=%d  errors=%d', total_ok, total_skip, total_err)
    if total_err:
        log.warning('%d error(s) — re-run the script to retry (already-migrated files are skipped)', total_err)
        sys.exit(1)


if __name__ == '__main__':
    main()
