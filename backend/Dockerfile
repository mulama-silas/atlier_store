FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=botique_backend.settings

WORKDIR /srv/app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Collect static assets (served by WhiteNoise) at image build time.
RUN python manage.py collectstatic --noinput

# Render injects PORT automatically; fall back to 8000 locally.
EXPOSE 8000
# Apply schema migrations before serving traffic. Render's free tier supports
# no pre-deploy command, so this runs on every container start (idempotent).
#
# ensure_superuser is the ONLY recovery path into the admin on the free plan:
# Render offers no shell, so there is no way to run createsuperuser by hand if
# the superuser is ever lost. It reads DJANGO_SUPERUSER_* from the environment,
# is idempotent, and re-promotes the account on every boot. With those variables
# unset it falls back to prompting, so it is chained with `|| true` and must
# never be able to stop the container from serving.
CMD ["sh", "-c", "python manage.py migrate --noinput && (echo y | python manage.py ensure_superuser --noinput 2>/dev/null || true) && gunicorn botique_backend.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 120 --max-requests 1000 --max-requests-jitter 100 --access-logfile -"]