from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache

def health_check(request):
    """
    Health check endpoint for production monitoring & load balancers.
    Checks DB and Cache status.
    """
    health_status = {
        "status": "healthy",
        "database": "unknown",
        "cache": "unknown"
    }

    # DB Check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_status["database"] = "connected"
    except Exception as e:
        health_status["database"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"

    # Cache Check
    try:
        cache.set("_health_check", 1, timeout=5)
        val = cache.get("_health_check")
        if val == 1:
            health_status["cache"] = "connected"
        else:
            health_status["cache"] = "degraded"
    except Exception as e:
        health_status["cache"] = f"error: {str(e)}"

    code = 200 if health_status["status"] == "healthy" else 503
    return JsonResponse(health_status, status=code)
