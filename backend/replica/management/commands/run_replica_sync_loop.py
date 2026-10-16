"""Run automatic replica checks from the web container without a scheduler service."""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from replica.services.sync import (
    ReplicaAlreadyRunning,
    get_connection,
    replica_configured,
    sync_replica,
)

logger = logging.getLogger(__name__)
SCHEDULER_LOCK_KEY = 'modeza_replica_auto_scheduler'


class Command(BaseCommand):
    help = 'Poll Django data and sync changes to the Supabase replica.'

    def handle(self, *args, **options):
        if not getattr(settings, 'REPLICA_AUTO_SYNC_ENABLED', False):
            self.stdout.write('Automatic replica sync is disabled.')
            return

        interval = max(
            10, int(getattr(settings, 'REPLICA_AUTO_SYNC_INTERVAL_SECONDS', 10)))
        self.stdout.write(
            f'Automatic replica sync enabled; checking every {interval} seconds.')

        while True:
            scheduler_conn = None
            try:
                if not replica_configured():
                    time.sleep(interval)
                    continue

                scheduler_conn = get_connection()
                scheduler_conn.autocommit = True
                with scheduler_conn.cursor() as cur:
                    cur.execute(
                        'SELECT pg_try_advisory_lock(hashtext(%s))',
                        (SCHEDULER_LOCK_KEY,),
                    )
                    is_leader = cur.fetchone()[0]

                if not is_leader:
                    scheduler_conn.close()
                    scheduler_conn = None
                    time.sleep(interval)
                    continue

                self._run_as_leader(scheduler_conn, interval)
            except KeyboardInterrupt:
                return
            except Exception:  # noqa: BLE001 - keep the daemon alive on outages
                logger.exception('Automatic replica scheduler could not connect.')
                time.sleep(interval)
            finally:
                if scheduler_conn is not None:
                    try:
                        scheduler_conn.close()
                    except Exception:  # noqa: BLE001
                        logger.debug('Could not close scheduler connection.',
                                     exc_info=True)

    def _run_as_leader(self, scheduler_conn, interval):
        self.stdout.write('This process is the automatic replica sync leader.')
        while True:
            started_at = time.monotonic()
            try:
                with scheduler_conn.cursor() as cur:
                    cur.execute('SELECT 1')
                    cur.fetchone()
            except Exception:  # noqa: BLE001 - reacquire after a lost lock session
                logger.warning('Automatic replica scheduler connection was lost.')
                return

            try:
                sync_replica(triggered_by='cron', include_storage=False)
                delay = interval
            except ReplicaAlreadyRunning:
                # A manual or token-triggered run has the sync lock; let it
                # finish and continue polling on the next interval.
                delay = interval
            except Exception:  # noqa: BLE001 - retry without stopping the web app
                logger.warning('Automatic replica sync failed; will retry.')
                delay = max(interval, 30)

            time.sleep(max(0, delay - (time.monotonic() - started_at)))
