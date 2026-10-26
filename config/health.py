from django.db import DatabaseError
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from config.readiness import SchemaNotReady, check_schema_ready


@require_safe
@never_cache
def liveness(request):
    """Confirm the HTTP process is alive, independently of its database."""
    return JsonResponse({'status': 'ok'})


@require_safe
@never_cache
def readiness(request):
    """Check database and required migration state without exposing internals."""
    try:
        check_schema_ready()
    except (DatabaseError, SchemaNotReady, InconsistentMigrationHistory):
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok'})
