from etims.services import get_kra_reference
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db import connections

from .models import DebitCredit


@api_view(["GET"])
def get_next_kra_reference(request):

    sent_items = (
        DebitCredit.objects
        .filter(etims_status="SENT")
        .order_by("created_at")
    )

    if not sent_items.exists():
        return Response({
            "success": True,
            "message": "No SENT transactions found"
        })

    processed = []
    failed = []

    for obj in sent_items:

        try:
            result = get_kra_reference(str(obj.source_pushnote_code))

            kra_ref = result.get("ref")
            kra_message = result.get("message")

            # -------------------------
            # Update local DB
            # -------------------------
            obj.kra_ref = kra_ref
            obj.kra_message = kra_message

            if kra_ref:
                obj.etims_status = "COMPLETED"

            obj.save()

            # -------------------------
            # Update external DB
            # -------------------------
            if kra_ref and obj.debit_credit_reference:
                with connections['default_betterlife'].cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE pushnote
                        SET pushnoteetimskraref = %s
                        WHERE pushnotedrcrnotenumber = %s
                        """,
                        [kra_ref, obj.debit_no]
                    )

            processed.append({
                "reference": obj.debit_credit_reference,
                "unique_ref": obj.source_pushnote_code,
                "kra_ref": kra_ref
            })

        except Exception as e:
            obj.last_error = str(e)
            obj.save()

            failed.append({
                "reference": obj.debit_credit_reference,
                "error": str(e)
            })

    return Response({
        "success": True,
        "processed_count": len(processed),
        "failed_count": len(failed),
        "processed": processed,
        "failed": failed
    })






# from etims.services import get_kra_reference
# from rest_framework.decorators import api_view
# from rest_framework.response import Response

# from .models import DebitCredit


# @api_view(["GET"])
# def get_next_kra_reference(request):

#     obj = (
#         DebitCredit.objects
#         .filter(etims_status="SENT")
#         .order_by("created_at")
#         .first()
#     )

#     if not obj:
#         return Response({
#             "success": True,
#             "message": "No SENT transactions found"
#         })

#     try:

#         result = get_kra_reference(
#             str(obj.source_pushnote_code)
#         )

#         obj.kra_ref = result.get("ref")
#         obj.kra_message = result.get("message")

#         if result.get("ref"):
#             obj.etims_status = "COMPLETED"

#         obj.save()

#         return Response({
#             "success": True,
#             "reference": obj.debit_credit_reference,
#             "unique_ref": obj.source_pushnote_code,
#             "kra_ref": result.get("ref"),
#             "message": result.get("message")
#         })

#     except Exception as e:

#         obj.last_error = str(e)
#         obj.save()

#         return Response({
#             "success": False,
#             "error": str(e)
#         }, status=500)