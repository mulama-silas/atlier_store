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
# creates the account only when missing, preserves an existing password, and
# restores admin flags if needed. Set DJANGO_SUPERUSER_RESET_PASSWORD=true for
# one deliberate password reset, then remove that flag.
CMD ["sh", "start.sh"]
