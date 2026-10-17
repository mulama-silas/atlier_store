import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Create or update a Django superuser from environment variables.

    Reads DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL,
    DJANGO_SUPERUSER_PASSWORD, DJANGO_SUPERUSER_FIRST_NAME and
    DJANGO_SUPERUSER_LAST_NAME. Useful in one-off shells (e.g. Render Shell)
    where interactively typing a password is inconvenient and where a plain
    ``createsuperuser`` would silently target the wrong database.

    The command is idempotent: an existing matching user is promoted to
    superuser/staff and its password refreshed when a password is provided.
    """

    help = 'Create a superuser (or refresh an existing one) using DJANGO_SUPERUSER_* environment variables.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            help='Superuser username (defaults to the DJANGO_SUPERUSER_USERNAME env var or "admin").',
        )
        parser.add_argument(
            '--email',
            help='Superuser email (defaults to the DJANGO_SUPERUSER_EMAIL env var).',
        )
        parser.add_argument(
            '--first-name',
            help='First name (defaults to DJANGO_SUPERUSER_FIRST_NAME).',
        )
        parser.add_argument(
            '--last-name',
            help='Last name (defaults to DJANGO_SUPERUSER_LAST_NAME).',
        )
        parser.add_argument(
            '--password',
            help='Superuser password (defaults to the DJANGO_SUPERUSER_PASSWORD env var; prompts if missing).',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        username = (options.get('username')
                    or self._env('DJANGO_SUPERUSER_USERNAME')
                    or 'admin')
        email = options.get('email') or self._env('DJANGO_SUPERUSER_EMAIL') or ''
        first_name = options.get('first_name') or self._env(
            'DJANGO_SUPERUSER_FIRST_NAME')
        last_name = options.get('last_name') or self._env(
            'DJANGO_SUPERUSER_LAST_NAME')
        password = options.get('password') or self._env('DJANGO_SUPERUSER_PASSWORD')

        if not email:
            self.stderr.write(self.style.WARNING(
                'No email provided (--email / DJANGO_SUPERUSER_EMAIL); attribute left empty.'))
        if not password:
            password = getpass.getpass('Password: ')
            confirm = getpass.getpass('Password (again): ')
            if password != confirm:
                raise CommandError('The two password fields didn\'t match.')
        if username.lower() == password.lower():
            raise CommandError('The password must not match the username.')

        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'is_active': True},
        )
        user.email = email or user.email
        user.first_name = first_name or user.first_name
        user.last_name = last_name or user.last_name
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(
                f'Superuser "{username}" created and granted admin powers.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Superuser "{username}" already existed; updated email/password and admin flags.'))

    @staticmethod
    def _env(name):
        import os
        return os.getenv(name, '')