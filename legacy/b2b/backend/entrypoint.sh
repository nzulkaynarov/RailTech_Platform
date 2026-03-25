#!/bin/sh
set -e

# Fix volume permissions (runs as root before dropping privileges)
chown -R appuser:appuser /app/staticfiles /app/media

# Execute the main command as appuser
exec gosu appuser "$@"
