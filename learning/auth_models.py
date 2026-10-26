"""Shared auth-abuse counters; never store submitted account identifiers or IPs."""
from django.db import models


class AuthRateBucket(models.Model):
    bucket_key = models.CharField(max_length=64, unique=True)
    action = models.CharField(max_length=20)
    scope = models.CharField(max_length=10, choices=[('ip', 'IP'), ('identifier', 'IP and identifier')])
    window_started_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    request_count = models.PositiveIntegerField(default=0)
