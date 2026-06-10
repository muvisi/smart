# services/etims_service.py

import requests


ETIMS_BASE_URL = "http://192.168.0.250:9090/etimsuat"


def create_medical_tax_transaction(payload):
    url = f"{ETIMS_BASE_URL}/medicalTaxTrans"
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def get_kra_reference(unique_ref):
    url = f"{ETIMS_BASE_URL}/queryKraRef"
    response = requests.get(url, params={"reference": unique_ref}, timeout=30)
    response.raise_for_status()
    return response.json()



from django.db import transaction
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import DebitCredit
from .services import create_medical_tax_transaction


@api_view(["POST"])
def send_next_debit(request):

    obj = DebitCredit.objects.filter(
        Q(etims_status="PENDING") | Q(etims_status="FAILED")
    ).order_by("created_at").first()

    if not obj:
        return Response({
            "success": True,
            "message": "No pending debits"
        })

    payload = {
        "debitCreditRef": obj.debit_credit_reference,
        "clientPin": obj.client_pin,
        "clientName": obj.client_name,
        "amount": float(obj.transaction_total_amount or 0),
        "uniqueRef": str(obj.source_pushnote_code),
        "originalReference": obj.debit_credit_reference,
    }

    try:
        with transaction.atomic():

            response = create_medical_tax_transaction(payload)

            obj.etims_status = "SENT"
            obj.save(update_fields=["etims_status", "updated_at"])

        return Response({
            "success": True,
            "message": "Sent to eTIMS",
            "data": response,
            "debit_credit_ref": obj.debit_credit_reference
        })

    except Exception as e:
        obj.etims_status = "FAILED"
        obj.kra_message = str(e)
        obj.save(update_fields=["etims_status", "kra_message", "updated_at"])

        return Response({
            "success": False,
            "error": str(e),
            "debit_credit_ref": obj.debit_credit_reference
        }, status=500)
        
        
from .services import get_kra_reference


@api_view(["POST"])
def resolve_next_kra(request):

    obj = DebitCredit.objects.filter(
        etims_status="SENT"
    ).order_by("created_at").first()

    if not obj:
        return Response({
            "success": True,
            "message": "No SENT records"
        })

    try:
        res = get_kra_reference(obj.source_pushnote_code)

        obj.kra_ref = res.get("ref")
        obj.kra_message = res.get("message")

        if res.get("ref"):
            obj.etims_status = "COMPLETED"

        obj.save()

        return Response({
            "success": True,
            "debit_credit_ref": obj.debit_credit_reference,
            "kra_ref": res.get("ref"),
            "message": res.get("message")
        })

    except Exception as e:
        obj.kra_message = str(e)
        obj.save()

        return Response({
            "success": False,
            "error": str(e)
        }, status=500)