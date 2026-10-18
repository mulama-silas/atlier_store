import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Create a Django superuser once, preserving existing credentials.

    Reads DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL,
    DJANGO_SUPERUSER_PASSWORD, DJANGO_SUPERUSER_FIRST_NAME and
    DJANGO_SUPERUSER_LAST_NAME. Useful in one-off shells (e.g. Render Shell)
    where interactively typing a password is inconvenient and where a plain
    ``createsuperuser`` would silently target the wrong database.

    The command is idempotent: an existing matching user keeps its password
    and profile. Missing staff/superuser flags are repaired. Password changes
    require the explicit --reset-password option.
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
            help='Password for a new account or with --reset-password (defaults to DJANGO_SUPERUSER_PASSWORD; prompts if missing).',
        )
        parser.add_argument(
            '--reset-password',
            action='store_true',
            help='Explicitly change the password of an existing matching user.',
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
        reset_password = options['reset_password']
        user = User.objects.filter(username=username).first()

        if user is not None:
            updated_fields = []
            for field in ('is_active', 'is_staff', 'is_superuser'):
                if not getattr(user, field):
                    setattr(user, field, True)
                    updated_fields.append(field)

            if reset_password:
                password = (
                    options.get('password')
                    or self._env('DJANGO_SUPERUSER_PASSWORD')
                )
                if not password:
                    password = self._prompt_password()
                self._validate_password(username, password)
                user.set_password(password)
                updated_fields.append('password')

            if updated_fields:
                user.save(update_fields=updated_fields)

            if reset_password:
                message = (
                    f'Superuser "{username}" already existed; admin access '
                    'was ensured and password reset explicitly.')
            elif updated_fields:
                message = (
                    f'Superuser "{username}" already existed; admin access '
                    'was restored without changing the password.')
            else:
                message = (
                    f'Superuser "{username}" already exists; left unchanged.')
            self.stdout.write(self.style.SUCCESS(message))
            return

        if not email:
            self.stderr.write(self.style.WARNING(
                'No email provided (--email / DJANGO_SUPERUSER_EMAIL); attribute left empty.'))
        password = (
            options.get('password')
            or self._env('DJANGO_SUPERUSER_PASSWORD')
        )
        if not password:
            password = self._prompt_password()
        self._validate_password(username, password)

        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
        )
        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        if first_name or last_name:
            user.save(update_fields=['first_name', 'last_name'])

        self.stdout.write(self.style.SUCCESS(
            f'Superuser "{username}" created.'))

    @staticmethod
    def _prompt_password():
        password = getpass.getpass('Password: ')
        confirm = getpass.getpass('Password (again): ')
        if password != confirm:
            raise CommandError('The two password fields didn\'t match.')
        return password

    @staticmethod
    def _validate_password(username, password):
        if username.lower() == password.lower():
            raise CommandError('The password must not match the username.')

    @staticmethod
    def _env(name):
        import os
        return os.getenv(name, '')
