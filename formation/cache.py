"""
Formation Cache Utilities — Redis-backed caching helpers.

Provides key generators and invalidation helpers for the formation app.
All cache operations go through Django's ``cache`` framework so
the backend (Redis / LocMem / DB) is transparent to callers.
"""

import hashlib
import json
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

# ── TTL Constants (seconds) ─────────────────────────────────────────────────

COURSE_LIST_TTL = 300        # 5 minutes
COURSE_DETAIL_TTL = 300      # 5 minutes
CATEGORY_LIST_TTL = 1800     # 30 minutes
SECTION_LIST_TTL = 300       # 5 minutes
ENROLLMENT_TTL = 600         # 10 minutes
CERTIFICATE_TTL = 3600       # 1 hour (immutable data)
WILAYA_TTL = 86400           # 24 hours (static data)


# ── Key Generators ──────────────────────────────────────────────────────────

def _hash_params(params: dict) -> str:
    """Create a short deterministic hash from query parameters."""
    stable = json.dumps(sorted(params.items()), default=str)
    return hashlib.md5(stable.encode()).hexdigest()[:12]


# Bump when a cached payload's shape or access rules change, so entries
# written by older code are never served again (v2: lesson files/text and
# material links are stripped from public responses).
CACHE_VERSION = 'v2'

# Access scopes that may share a cache (see content_access.ContentAccess).
CACHE_SCOPES = ('public', 'admin')


def course_list_key(query_params: dict, is_admin: bool = False) -> str:
    """Cache key for the course catalog list view."""
    prefix = 'course_list_admin' if is_admin else 'course_list'
    h = _hash_params(query_params)
    return f'{prefix}:{CACHE_VERSION}:{h}'


def course_detail_key(slug: str, scope: str = 'public') -> str:
    return f'course_detail:{CACHE_VERSION}:{scope}:{slug}'


def category_list_key() -> str:
    return 'categories:all'


def section_list_key(query_params: dict, scope: str = 'public') -> str:
    h = _hash_params(query_params)
    return f'section_list:{CACHE_VERSION}:{scope}:{h}'


def enrollment_key(user_id, course_id) -> str:
    return f'enrolled:{user_id}:{course_id}'


def certificate_verify_key(code: str) -> str:
    return f'certificate:{code}'


def wilaya_list_key() -> str:
    return 'wilayas:all'


# ── Invalidation Helpers ────────────────────────────────────────────────────

def _delete_pattern(pattern: str) -> None:
    """
    Delete all keys matching *pattern*.

    Uses ``cache.delete_pattern`` if the backend supports it (django-redis).
    Falls back to a no-op for backends like LocMemCache that lack glob support.
    """
    delete_fn = getattr(cache, 'delete_pattern', None)
    if callable(delete_fn):
        try:
            delete_fn(f'*{pattern}*')
        except Exception:
            logger.debug('delete_pattern unavailable, skipping: %s', pattern)
    else:
        logger.debug('Cache backend does not support delete_pattern')


def invalidate_course_list() -> None:
    """Bust all cached course list pages (admin & public)."""
    _delete_pattern('course_list')


def invalidate_course_detail(slug: str) -> None:
    """Bust a single course's detail cache entries (every access scope)."""
    cache.delete_many([course_detail_key(slug, scope) for scope in CACHE_SCOPES])


def invalidate_course_caches(slug: str | None = None) -> None:
    """Convenience: bust all course-related caches at once."""
    invalidate_course_list()
    if slug:
        invalidate_course_detail(slug)


def invalidate_categories() -> None:
    cache.delete(category_list_key())


def invalidate_sections() -> None:
    _delete_pattern('section_list')


def invalidate_enrollment(user_id, course_id) -> None:
    cache.delete(enrollment_key(user_id, course_id))


def invalidate_certificate(code: str) -> None:
    cache.delete(certificate_verify_key(code))
