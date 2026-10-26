"""Serialize non-key edits without blocking PostgreSQL foreign-key references."""
from django.db import connections


def nonkey_row_lock(queryset):
    # FOR NO KEY UPDATE remains mutually exclusive with another writer, while
    # allowing admin-log/other inserts to take a foreign-key KEY SHARE lock.
    # SQLite has no row locks; unsupported backends retain their usual lock.
    features = connections[queryset.db].features
    options = {'no_key': True} if features.has_select_for_no_key_update else {}
    return queryset.select_for_update(**options)
