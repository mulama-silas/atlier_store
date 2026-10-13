"""Mirror the Supabase product-image bucket into a private backup bucket.

Database backups do not cover Storage objects -- Supabase's own docs are
explicit that a restore returns metadata only, never the bytes. So the images
need a copy of their own.

The destination bucket must be created once in the dashboard (or the Storage
API) as **private**: a backup copy that is publicly served is not a backup, it
is a second public copy of the catalogue.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Supabase Storage returns at most this many entries per list call.
PAGE_SIZE = 1000


def _clients():
    """(admin_client, source_bucket, dest_bucket) or raise a clear error.

    Validation happens before the client is built, so a misconfiguration
    fails immediately without opening a connection.
    """
    url = getattr(settings, 'SUPABASE_URL', '').strip()
    key = getattr(settings, 'SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not url or not key:
        raise RuntimeError(
            'SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set to '
            'mirror the image bucket.'
        )
    source = getattr(settings, 'SUPABASE_STORAGE_BUCKET', 'product-images')
    dest = getattr(settings, 'REPLICA_BACKUP_BUCKET', 'product-images-backup')
    if not dest:
        raise RuntimeError('REPLICA_BACKUP_BUCKET is not configured.')
    if source == dest:
        raise RuntimeError(
            f'REPLICA_BACKUP_BUCKET ({dest}) must differ from '
            f'SUPABASE_STORAGE_BUCKET ({source}).'
        )

    from supabase import create_client

    # Same two-argument form as botique_backend.storage.SupabaseStorage, so
    # this stays compatible with the installed supabase-py version.
    return create_client(url, key), source, dest


def _list_all(client, bucket, prefix):
    """Recursively yield every object key under ``prefix``."""
    stack = [prefix]
    while stack:
        path = stack.pop()
        offset = 0
        while True:
            result = client.storage.from_(bucket).list(
                path, {'limit': PAGE_SIZE, 'offset': offset}
            )
            entries = result if isinstance(result, list) else []
            if not entries:
                break
            for entry in entries:
                name = entry.get('name')
                if not name:
                    continue
                key = f'{path}/{name}'.strip('/')
                # Storage reports folders with a null id and no metadata.
                if entry.get('id') is None and entry.get('metadata') in (None, {}):
                    stack.append(key)
                else:
                    yield key
            offset += PAGE_SIZE
            if len(entries) < PAGE_SIZE:
                break


def mirror_bucket(limit=None):
    """Copy every object from the source bucket to the backup bucket.

    Existing objects are overwritten (``upsert``), so the mirror is safe to
    re-run and converges rather than accumulating versions.
    """
    admin, source, dest = _clients()

    copied, skipped, bytes_copied = 0, 0, 0
    for key in _list_all(admin, source, ''):
        if limit is not None and copied + skipped >= limit:
            logger.info('Storage mirror stopped at limit=%s', limit)
            break

        data = admin.storage.from_(source).download(key)
        # supabase-py returns the raw bytes, or a 1-tuple in older versions.
        if isinstance(data, tuple):
            data = data[0]
        if not data:
            skipped += 1
            continue

        admin.storage.from_(dest).upload(key, data, {'upsert': 'true'})
        copied += 1
        bytes_copied += len(data)

    result = {
        'status': 'ok',
        'source_bucket': source,
        'dest_bucket': dest,
        'objects_copied': copied,
        'objects_skipped': skipped,
        'bytes_copied': bytes_copied,
    }
    logger.info('Storage mirror: %s', result)
    return result