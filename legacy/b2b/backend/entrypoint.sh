#!/bin/sh
set -e

# Fix volume permissions (runs as root before dropping privileges)
chown -R appuser:appuser /app/staticfiles /app/media

# Run DB migrations + collectstatic ONLY for the web server process.
# The same image powers backend (gunicorn/daphne), celery-worker and celery-beat;
# migrating from all three on boot would race. Gate on the launched command.
case "$1" in
    gunicorn | daphne)
        # INF-04: prod deploys take a pg_dump FIRST and then apply migrations
        # explicitly (deploy-b2b.yml sets AUTO_MIGRATE=false) — a container
        # restart must never mutate the schema without a backup gate. The
        # default stays true so local/dev `make up` keeps its zero-step boot.
        if [ "${AUTO_MIGRATE:-true}" = "true" ]; then
            echo "[entrypoint] Applying database migrations..."
            gosu appuser python manage.py migrate --noinput
        else
            echo "[entrypoint] AUTO_MIGRATE=false — skipping migrations (deploy applies them explicitly after the backup gate)"
        fi
        echo "[entrypoint] Collecting static files..."
        gosu appuser python manage.py collectstatic --noinput
        ;;
esac

# Execute the main command as appuser
exec gosu appuser "$@"
