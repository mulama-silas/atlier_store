"""Supabase analytics replica.

Mirrors the Django system of record into the Supabase ``replica`` schema for
reporting, and keeps a nightly catalogue snapshot history. It is NOT a
disaster-recovery target -- Django cannot be repointed at this schema.

See ``supabase/replica_schema.sql`` for the schema and the security model.
"""

default_app_config = 'replica.apps.ReplicaConfig'