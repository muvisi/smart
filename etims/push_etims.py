
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import DebitCredit
from .services import create_medical_tax_transaction


@api_view(["POST"])
def send_next_transaction(request):

    pending_items = (
        DebitCredit.objects
        .filter(Q(etims_status="PENDING") | Q(etims_status="FAILED"))
        .order_by("created_at")
    )

    if not pending_items.exists():
        return Response({
            "success": True,
            "message": "No pending transactions found"
        })

    processed = []
    failed = []

    for obj in pending_items:

        payload = {
            "debitCreditRef": obj.debit_credit_reference,
            "clientPin": obj.client_pin,
            "clientName": obj.client_name,
            "amount": float(obj.transaction_total_amount or 0),
            "uniqueRef": str(obj.source_pushnote_code),
            "originalReference": None
        }

        try:
            response = create_medical_tax_transaction(payload)

            obj.etims_status = "SENT"
            obj.last_synced_at = timezone.now()
            obj.kra_message = str(response)
            obj.last_error = None
            obj.save()

            processed.append({
                "reference": obj.debit_credit_reference,
                "status": "SENT",
                "response": response
            })

        except Exception as e:

            obj.etims_status = "FAILED"
            obj.last_error = str(e)
            obj.save()

            failed.append({
                "reference": obj.debit_credit_reference,
                "status": "FAILED",
                "error": str(e)
            })

    return Response({
        "success": True,
        "processed_count": len(processed),
        "failed_count": len(failed),
        "processed": processed,
        "failed": failed
    })
    
    
# @api_view(["POST"])
# def send_next_transaction(request):

#     obj = (
#         DebitCredit.objects
#         .filter(Q(etims_status="PENDING") | Q(etims_status="FAILED"))
#         .order_by("created_at")
#         .first()
#     )

#     if not obj:
#         return Response({
#             "success": True,
#             "message": "No pending transactions found"
#         })

#     payload = {
#         "debitCreditRef": obj.debit_credit_reference,
#         "clientPin": obj.client_pin,
#         "clientName": obj.client_name,
#         "amount": float(obj.transaction_total_amount or 0),
#         "uniqueRef": str(obj.source_pushnote_code),
#         "originalReference": None
#     }

#     try:
#         response = create_medical_tax_transaction(payload)

#         obj.etims_status = "SENT"
#         obj.last_synced_at = timezone.now()
#         obj.kra_message = str(response)
#         obj.last_error = None
#         obj.save()

#         return Response({
#             "success": True,
#             "message": "Transaction sent successfully",
#             "reference": obj.debit_credit_reference,
#             "response": response
#         })

#     except Exception as e:

#         obj.etims_status = "FAILED"
#         obj.last_error = str(e)
#         obj.save()

#         return Response({
#             "success": False,
#             "reference": obj.debit_credit_reference,
#             "error": str(e)
#         }, status=500)