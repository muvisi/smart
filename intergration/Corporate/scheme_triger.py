from django.http import JsonResponse

from intergration.Corporate.schemes import SmartSyncService
# from .services import SmartSyncService

def trigger_smart_sync(request):
    """
    Public endpoint to trigger the sync process.
    Best practiced: Use a service class to keep views thin.
    """
    service = SmartSyncService()
    result = service.run_sync()
    
    status_code = 200 if result.get('status') == 'success' else 500
    return JsonResponse(result, status=status_code)