#!/usr/bin/env bash
# =============================================================================
# OOSkills — one-time STAGING setup on the VPS
#
# Creates a second, fully separate copy of OOSkills next to production:
#
#   production:  /var/www/ooskills/          ooskills-backend / ooskills-frontend
#   staging:     /var/www/ooskills-staging/  ooskills-backend-staging (:8001)
#                                            ooskills-frontend-staging (:3001)
#
# Safe to re-run: every step checks what already exists. It never touches the
# production directories or services (it only reads their git remote URLs).
#
# Run as root:   bash setup-staging.sh
# =============================================================================
set -euo pipefail

PROD_ROOT=/var/www/ooskills
STAGING_ROOT=/var/www/ooskills-staging
BACKEND_DIR=$STAGING_ROOT/ooskills-backend
FRONTEND_DIR=$STAGING_ROOT/ooskills-frontend
BRANCH=staging
APP_USER=ooskills
API_HOST=api-staging.ooskills.com
WEB_HOST=staging.ooskills.com

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
as_app() { su - "$APP_USER" -c "set -e; $*"; }

# --- 0. Preconditions ---------------------------------------------------------
[ "$(id -u)" -eq 0 ] || fail "Run this as root."
id "$APP_USER" >/dev/null 2>&1 || fail "User '$APP_USER' does not exist."
[ -d "$PROD_ROOT/ooskills-backend/.git" ]  || fail "Production backend not found at $PROD_ROOT/ooskills-backend."
[ -d "$PROD_ROOT/ooskills-frontend/.git" ] || fail "Production frontend not found at $PROD_ROOT/ooskills-frontend."

for port in 8001 3001; do
  if ss -ltn "sport = :$port" | grep -q LISTEN; then
    systemctl is-active --quiet ooskills-backend-staging ooskills-frontend-staging 2>/dev/null \
      || fail "Port $port is already in use by something else. Pick another port in the .service files and nginx config."
  fi
done

# Reuse production's remotes so the same git credentials / deploy key work.
BACKEND_REMOTE=$(git -C "$PROD_ROOT/ooskills-backend" remote get-url origin)
FRONTEND_REMOTE=$(git -C "$PROD_ROOT/ooskills-frontend" remote get-url origin)

# --- 1. Directories -------------------------------------------------------------
say "Creating $STAGING_ROOT"
mkdir -p "$STAGING_ROOT"
chown "$APP_USER:$APP_USER" "$STAGING_ROOT"

# --- 2. Clone the staging branch of both repos -------------------------------
clone_or_update() {  # $1 = remote, $2 = dir
  if [ -d "$2/.git" ]; then
    say "Updating $2"
    as_app "cd '$2' && git fetch origin && git checkout $BRANCH && git reset --hard origin/$BRANCH"
  else
    say "Cloning $BRANCH into $2"
    as_app "git clone --branch $BRANCH '$1' '$2'" \
      || fail "Could not clone branch '$BRANCH'. Push a '$BRANCH' branch to $1 first."
  fi
}
clone_or_update "$BACKEND_REMOTE"  "$BACKEND_DIR"
clone_or_update "$FRONTEND_REMOTE" "$FRONTEND_DIR"

# --- 3. Backend environment ---------------------------------------------------
if [ ! -f "$BACKEND_DIR/.env" ]; then
  cp "$BACKEND_DIR/deploy/staging/backend.env.example" "$BACKEND_DIR/.env"
  chown "$APP_USER:$APP_USER" "$BACKEND_DIR/.env"
  chmod 600 "$BACKEND_DIR/.env"
  fail "Created $BACKEND_DIR/.env from the template. Fill in every value (separate DB, test Chargily keys, staging buckets), then re-run this script."
fi
grep -q '^ENVIRONMENT=staging' "$BACKEND_DIR/.env" \
  || fail "$BACKEND_DIR/.env must contain ENVIRONMENT=staging."
grep -q '^R2_BUCKET_PREFIX=.\+' "$BACKEND_DIR/.env" \
  || fail "$BACKEND_DIR/.env must set R2_BUCKET_PREFIX (e.g. staging-) so staging can't touch production files."

# Refuse to run if staging's DB host is production's DB host.
prod_db=$(grep -E '^DB_HOST=' "$PROD_ROOT/ooskills-backend/.env" 2>/dev/null | cut -d= -f2- || true)
stg_db=$(grep -E '^DB_HOST=' "$BACKEND_DIR/.env" | cut -d= -f2-)
prod_user=$(grep -E '^DB_USER=' "$PROD_ROOT/ooskills-backend/.env" 2>/dev/null | cut -d= -f2- || true)
stg_user=$(grep -E '^DB_USER=' "$BACKEND_DIR/.env" | cut -d= -f2-)
if [ -n "$prod_db" ] && [ "$prod_db" = "$stg_db" ] && [ "$prod_user" = "$stg_user" ]; then
  fail "Staging .env points at the PRODUCTION database ($stg_db). Use a separate Supabase project."
fi

# --- 4. Backend install ---------------------------------------------------------
say "Installing backend"
as_app "cd '$BACKEND_DIR' && [ -d venv ] || python3 -m venv venv"
as_app "cd '$BACKEND_DIR' && venv/bin/pip install -q --upgrade pip && venv/bin/pip install -q -r requirements.txt"
as_app "cd '$BACKEND_DIR' && venv/bin/python manage.py check --deploy --fail-level ERROR"
as_app "cd '$BACKEND_DIR' && venv/bin/python manage.py migrate --noinput"
as_app "cd '$BACKEND_DIR' && venv/bin/python manage.py collectstatic --noinput"

# --- 5. Frontend install --------------------------------------------------------
say "Installing frontend"
FRONT_ENV="$FRONTEND_DIR/.env.production.local"
if [ ! -f "$FRONT_ENV" ]; then
  {
    echo "NEXT_PUBLIC_API_URL=https://$API_HOST/api"
    # Public OAuth client IDs: reuse production's (add the staging origin in
    # the Google / Facebook consoles), or replace with staging-specific apps.
    for f in .env.production.local .env.production .env.local .env; do
      p="$PROD_ROOT/ooskills-frontend/$f"
      [ -f "$p" ] && grep -E '^NEXT_PUBLIC_(GOOGLE_CLIENT_ID|FACEBOOK_APP_ID)=' "$p" && break
    done
  } > "$FRONT_ENV" || true
  chown "$APP_USER:$APP_USER" "$FRONT_ENV"
fi
as_app "cd '$FRONTEND_DIR' && npm ci && npm run build"

# --- 6. systemd services --------------------------------------------------------
say "Installing systemd services"
install -m 644 "$BACKEND_DIR/deploy/staging/ooskills-backend-staging.service"  /etc/systemd/system/
install -m 644 "$BACKEND_DIR/deploy/staging/ooskills-frontend-staging.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ooskills-backend-staging ooskills-frontend-staging
systemctl restart ooskills-backend-staging ooskills-frontend-staging

# --- 7. nginx ------------------------------------------------------------------
say "Configuring nginx"
if [ ! -f /etc/nginx/sites-available/ooskills-staging ]; then
  install -m 644 "$BACKEND_DIR/deploy/staging/nginx-staging.conf" /etc/nginx/sites-available/ooskills-staging
fi
ln -sf /etc/nginx/sites-available/ooskills-staging /etc/nginx/sites-enabled/ooskills-staging
nginx -t
systemctl reload nginx

# --- 8. Smoke test --------------------------------------------------------------
say "Checking services"
sleep 3
curl -fsS -H "Host: $API_HOST" http://127.0.0.1:8001/api/health/ && echo
curl -fsS -o /dev/null -w "frontend HTTP %{http_code}\n" http://127.0.0.1:3001/

say "Staging is running."
cat <<EOF

Next:
  1. DNS: point $WEB_HOST and $API_HOST (A records) at this server.
  2. HTTPS: certbot --nginx -d $WEB_HOST -d $API_HOST
  3. Open https://$API_HOST/api/health/  → should say "environment": "staging"
  4. From now on, every push to the '$BRANCH' branch deploys here automatically.
EOF
