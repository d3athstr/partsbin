#!/bin/bash
#
# PartsBin - idempotent VM bootstrap (Ubuntu 24.04, VM 121 "partsbin")
#
# Installs OS deps, creates the deploy user, PostgreSQL role/database, the
# Python venv, .env from template, runs migrations and installs the systemd
# units + nginx vhost. Safe to re-run.
#
set -euo pipefail

APP_DIR=/opt/partsbin
BACKEND_DIR=$APP_DIR/backend
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_NAME=partsbin
DB_USER=partsbin

echo "== PartsBin setup =="

if [[ $EUID -ne 0 ]]; then
    echo "Run as root." >&2
    exit 1
fi

# ---------- OS packages ----------
echo "-- apt dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    postgresql libpq-dev \
    python3-venv python3-dev build-essential \
    libmagic1 \
    nginx \
    git

# ---------- deploy user ----------
if ! id deploy &>/dev/null; then
    echo "-- creating deploy user"
    useradd --system --create-home --shell /usr/sbin/nologin deploy
fi

# ---------- app tree ----------
echo "-- syncing $REPO_DIR -> $APP_DIR"
mkdir -p "$APP_DIR"
if [[ "$REPO_DIR" != "$APP_DIR" ]]; then
    rsync -a --delete \
        --exclude venv --exclude node_modules --exclude .env --exclude uploads \
        "$REPO_DIR/" "$APP_DIR/"
fi
mkdir -p "$APP_DIR/uploads/components" "$APP_DIR/uploads/projects"
mkdir -p /etc/partsbin
chown -R deploy:deploy "$APP_DIR" /etc/partsbin
chmod 700 /etc/partsbin

# ---------- PostgreSQL ----------
echo "-- postgresql role + database"
DB_PASS_FILE=/etc/partsbin/db-password
if [[ ! -f $DB_PASS_FILE ]]; then
    openssl rand -hex 24 > "$DB_PASS_FILE"
    chown deploy:deploy "$DB_PASS_FILE"
    chmod 600 "$DB_PASS_FILE"
fi
DB_PASS="$(cat "$DB_PASS_FILE")"

sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS'"
sudo -u postgres psql -c "ALTER ROLE $DB_USER WITH PASSWORD '$DB_PASS'" >/dev/null
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"

# ---------- Python venv ----------
echo "-- python venv"
if [[ ! -d $BACKEND_DIR/venv ]]; then
    sudo -u deploy python3 -m venv "$BACKEND_DIR/venv"
fi
sudo -u deploy "$BACKEND_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u deploy "$BACKEND_DIR/venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt" -q

# ---------- .env ----------
if [[ ! -f $BACKEND_DIR/.env ]]; then
    echo "-- creating .env from template (fill in secrets from Vault: secret/<org>/partsbin/*)"
    cp "$APP_DIR/deployment/.env.example" "$BACKEND_DIR/.env"
    SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    ENC_KEY=$("$BACKEND_DIR/venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
    INGEST_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
    sed -i \
        -e "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" \
        -e "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENC_KEY|" \
        -e "s|^INGEST_KEY=.*|INGEST_KEY=$INGEST_KEY|" \
        -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost/$DB_NAME|" \
        "$BACKEND_DIR/.env"
    chown root:deploy "$BACKEND_DIR/.env"
    chmod 640 "$BACKEND_DIR/.env"
fi

# ---------- database schema ----------
echo "-- database schema"
cd "$BACKEND_DIR"
if [[ -d migrations ]]; then
    sudo -u deploy env FLASK_APP=run.py "$BACKEND_DIR/venv/bin/flask" db upgrade
else
    sudo -u deploy "$BACKEND_DIR/venv/bin/python" -c \
        "from app import create_app, db; app = create_app('production'); \
         ctx = app.app_context(); ctx.push(); db.create_all(); print('db.create_all() done')"
fi

# ---------- seed (categories + bootstrap invitation) ----------
sudo -u deploy env FLASK_APP=run.py "$BACKEND_DIR/venv/bin/flask" seed

# ---------- systemd ----------
echo "-- systemd units"
install -m 644 "$APP_DIR"/deployment/partsbin.service /etc/systemd/system/
install -m 644 "$APP_DIR"/deployment/partsbin-ingest.service /etc/systemd/system/
install -m 644 "$APP_DIR"/deployment/partsbin-ingest.timer /etc/systemd/system/
install -m 644 "$APP_DIR"/deployment/partsbin-token-monitor.service /etc/systemd/system/
install -m 644 "$APP_DIR"/deployment/partsbin-token-monitor.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now partsbin.service
systemctl enable --now partsbin-ingest.timer
systemctl enable --now partsbin-token-monitor.timer

# ---------- nginx ----------
echo "-- nginx vhost"
install -m 644 "$APP_DIR/deployment/nginx-partsbin.conf" /etc/nginx/sites-available/partsbin
ln -sf /etc/nginx/sites-available/partsbin /etc/nginx/sites-enabled/partsbin
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "== Done. Punch list =="
echo " * Fill Google/Anthropic/SMTP secrets into $BACKEND_DIR/.env (from Vault secret/<org>/partsbin/*)"
echo " * Build the frontend into $APP_DIR/frontend/dist"
echo " * Register with: the invitation code printed by 'flask seed' above"
echo " * Authorize Gmail accounts: /api/oauth/login/<user>?key=<INGEST_KEY>"
