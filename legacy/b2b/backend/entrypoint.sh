#!/bin/sh
set -e

# Fix volume permissions (runs as root before dropping privileges)
chown -R appuser:appuser /app/staticfiles /app/media

# Run DB migrations + collectstatic ONLY for the web server process.
# The same image powers backend (gunicorn/daphne), celery-worker and celery-beat;
# migrating from all three on boot would race. Gate on the launched command.
case "$1" in
    gunicorn | daphne)
        echo "[entrypoint] Applying database migrations..."
        gosu appuser python manage.py migrate --noinput
        echo "[entrypoint] Collecting static files..."
        gosu appuser python manage.py collectstatic --noinput
        ;;
esac

# Execute the main command as appuser
exec gosu appuser "$@"
