"""One shared request ledger for all tutor providers and editor AI drafts."""
from django.db import models


class GlobalTutorUsageBudget(models.Model):
    key = models.CharField(max_length=16, primary_key=True, default='tutor', editable=False)
    day = models.DateField()
    day_count = models.PositiveIntegerField(default=0)
    minute_started_at = models.DateTimeField()
    minute_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(key='tutor'), name='global_tutor_budget_singleton'),
        ]
