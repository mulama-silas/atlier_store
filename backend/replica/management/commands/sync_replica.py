"""``manage.py sync_replica`` -- mirror Django into Supabase, or inspect status.

This is the manual entry point. ``--status`` is read-only and safe to run
anywhere; the write paths are what the admin page and the cron endpoint call.
"""

from django.core.management.base import BaseCommand, CommandError

from replica.services.sync import (
    ReplicaNotConfigured,
    ReplicaStatusUnavailable,
    latest_run,
    replica_configured,
    sync_replica,
)


class Command(BaseCommand):
    help = (
        'Mirror the Django system of record into the Supabase replica schema, '
        'append a catalogue snapshot, and mirror the image bucket.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--triggered-by', default='manual',
            choices=['cron', 'manual', 'first'],
            help='How this run was initiated (recorded in replica.sync_runs).')
        parser.add_argument(
            '--skip-storage', action='store_true',
            help='Skip the image bucket mirror (relational replica only).')
        parser.add_argument(
            '--storage-limit', type=int, default=None,
            help='Copy at most N storage objects. Useful for a first trial run.')
        parser.add_argument(
            '--status', action='store_true',
            help='Print the most recent run and exit without writing anything.')

    def handle(self, *args, **options):
        if options['status']:
            return self._show_status()

        if not replica_configured():
            raise CommandError(
                'SUPABASE_DB_URL is not configured. Add it as a secret and '
                'redeploy before syncing.'
            )

        if options['storage_limit'] is not None and not options['skip_storage']:
            from replica.services.storage_mirror import mirror_bucket
            # Honour --storage-limit by mirroring on its own first, so the
            # relational sync does not redo it.
            info = mirror_bucket(limit=options['storage_limit'])
            self.stdout.write(self.style.WARNING(
                f'Storage mirrored separately with limit='
                f'{options["storage_limit"]}: {info}'
            ))

        try:
            summary = sync_replica(
                triggered_by=options['triggered_by'],
                include_storage=not options['skip_storage']
                and options['storage_limit'] is None,
            )
        except ReplicaNotConfigured as exc:
            raise CommandError(str(exc)) from exc
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS('Replica sync finished.'))
        for table, counts in summary['counts'].items():
            if not isinstance(counts, dict) or 'source' not in counts:
                continue
            self.stdout.write(
                f'  {table:<24} django={counts["source"]:<7} '
                f'supabase={counts["replica"]}'
            )
        if summary['storage']:
            self.stdout.write(f'  storage: {summary["storage"]}')

    def _show_status(self):
        if not replica_configured():
            self.stdout.write(self.style.WARNING(
                'SUPABASE_DB_URL is not configured; the replica is unreachable.'
            ))
            return
        try:
            run = latest_run()
        except ReplicaStatusUnavailable as exc:
            self.stdout.write(self.style.ERROR(
                f'Replica status unavailable: {exc}'
            ))
            return
        if not run:
            self.stdout.write(self.style.WARNING(
                'The replica is reachable but has no sync runs recorded yet.'
            ))
            return
        self.stdout.write(
            f'Run #{run["id"]}  {run["status"]}  '
            f'(triggered_by={run["triggered_by"]})\n'
            f'  started_at:  {run["started_at"]}\n'
            f'  finished_at: {run["finished_at"]}'
        )
        if run['error']:
            self.stdout.write(self.style.ERROR(f'  error: {run["error"]}'))
        for table, counts in (run['table_counts'] or {}).items():
            if isinstance(counts, dict) and 'source' in counts:
                self.stdout.write(
                    f'  {table:<24} django={counts["source"]:<7} '
                    f'supabase={counts["replica"]}'
                )