"""
Test-only settings — isolated in-memory SQLite.

Never touches any external/production database. Used for running the
authorization and business-logic test suites locally and in a pinch where a
Postgres service isn't available (CI still runs the same tests on Postgres 16).

Run with:  python manage.py test --settings=ooskillsbackend.settings_test
"""
import os

# Ensure base settings don't choke on a missing SECRET_KEY when .env is absent.
os.environ.setdefault('SECRET_KEY', 'test-only-secret-key-not-for-production')
os.environ.setdefault('DB_NAME', 'unused')
os.environ.setdefault('DB_USER', 'unused')
os.environ.setdefault('DB_PASSWORD', 'unused')
os.environ.setdefault('DB_HOST', 'localhost')

from ooskillsbackend.settings import *  # noqa: F401,F403,E402

# ---------------------------------------------------------------------------
# In-memory SQLite. Fast, disposable, and physically incapable of reaching the
# production Supabase host configured in .env.
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}


# ---------------------------------------------------------------------------
# Skip migrations: build the schema straight from model state. This avoids
# migration 0030's Postgres-only TrigramExtension / gin_trgm_ops operations.
# ---------------------------------------------------------------------------
class _DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMigrations()

# Faster password hashing during tests.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Keep tests hermetic: no real network throttling cache dependencies.
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# Neutralize DRF throttling during tests so authorization assertions are
# deterministic. We keep every scope *defined* (viewsets like EnrollmentViewSet
# hard-code ScopedRateThrottle, which raises if its scope has no rate) but set
# the limits absurdly high so nothing throttles.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {
        scope: '100000/second'
        for scope in REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
    },
}


# ---------------------------------------------------------------------------
# Neutralize Postgres-only GIN indexes when building the SQLite schema. Two
# GinIndexes live on the Course model; SQLite can't emit `USING gin`, so on any
# non-PostgreSQL backend we replace their DDL with a harmless no-op. Production
# and CI (both Postgres) are unaffected — the original path runs there.
# ---------------------------------------------------------------------------
from django.contrib.postgres.indexes import PostgresIndex  # noqa: E402
from django.db.backends.ddl_references import Statement  # noqa: E402

_orig_create_sql = PostgresIndex.create_sql
_orig_remove_sql = PostgresIndex.remove_sql


def _noop_create_sql(self, model, schema_editor, using='', **kwargs):
    if schema_editor.connection.vendor != 'postgresql':
        return Statement('SELECT 1', **{})
    return _orig_create_sql(self, model, schema_editor, using=using, **kwargs)


def _noop_remove_sql(self, model, schema_editor, **kwargs):
    if schema_editor.connection.vendor != 'postgresql':
        return Statement('SELECT 1', **{})
    return _orig_remove_sql(self, model, schema_editor, **kwargs)


PostgresIndex.create_sql = _noop_create_sql
PostgresIndex.remove_sql = _noop_remove_sql
