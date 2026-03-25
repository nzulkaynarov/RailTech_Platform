from django.http import JsonResponse
from django.db import connection

def health_check(request):
    """
    Simple health check endpoint for Docker/K8s.
    Returns 200 if the service is up and database is responsive.
    """
    health_status = {
        "status": "unhealthy",
        "database": "down",
    }
    
    try:
        # Check database connection
        connection.ensure_connection()
        health_status["database"] = "up"
        health_status["status"] = "healthy"
        return JsonResponse(health_status, status=200)
    except Exception as e:
        health_status["error"] = str(e)
        return JsonResponse(health_status, status=503)
