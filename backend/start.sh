#!/bin/sh

python manage.py migrate --noinput || exit $?
if [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  python manage.py ensure_superuser || exit $?
fi

# Keep the change-detecting sync loop in the same container as Django so it
# needs no external scheduler or separately billed worker service.
python manage.py run_replica_sync_loop &
sync_pid=$!

gunicorn botique_backend.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --threads 4 \
  --timeout 120 \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  --access-logfile - &
web_pid=$!

shutdown() {
  kill -TERM "$web_pid" "$sync_pid" 2>/dev/null || true
  wait "$web_pid" 2>/dev/null || true
  wait "$sync_pid" 2>/dev/null || true
}

trap shutdown INT TERM
wait "$web_pid"
status=$?
shutdown
exit "$status"
