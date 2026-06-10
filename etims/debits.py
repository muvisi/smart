# views.py

# from django.db import connections
from etims.serializer import DebitCreditSerializer
from etims.services import create_medical_tax_transaction, get_kra_reference
from rest_framework.views import APIView
from rest_framework.response import Response
# from rest_framework import status

from django.db import connections, transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import DebitCredit


@api_view(['GET'])
def sync_debit_credit_notes(request):
    query = """
    SELECT
        p.pushnotedrcrnotenumber AS "debitCreditRef",
        c.customerskrapin AS "clientPin",
        p.pushnotecode AS "uniqueRef",
        pt.transactionscode AS "transactionCode",
        t.transactionstotalamount AS "transactionTotalAmount",
        CASE
            WHEN c.customersname IS NOT NULL
                 AND TRIM(c.customersname) <> ''
            THEN c.customersname
            ELSE TRIM(
                COALESCE(c.customersfirstname, '') || ' ' ||
                COALESCE(c.customerssecondname, '') || ' ' ||
                COALESCE(c.customerslastname, '')
            )
        END AS "clientName"
    FROM pushnote p
    LEFT JOIN customers c
        ON p.customerscode = c.customerscode
    LEFT JOIN pushnotetransaction pt
        ON p.pushnotecode = pt.pushnotecode
    LEFT JOIN transactions t
        ON t.transactionscode = pt.transactionscode
    """

    try:
        with connections['default_betterlife'].cursor() as cursor:
            cursor.execute(query)

            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for row in rows:
                _, created = DebitCredit.objects.update_or_create(
                    debit_credit_reference=row["debitCreditRef"],
                    defaults={
                        "source_pushnote_code": row["uniqueRef"],
                        "transaction_code": row["transactionCode"],
                        "client_pin": row["clientPin"],
                        "client_name": row["clientName"],
                        "transaction_total_amount": row["transactionTotalAmount"],
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

        return Response(
            {
                "success": True,
                "created": created_count,
                "updated": updated_count,
                "total_processed": len(rows)
            },
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {
                "success": False,
                "error": str(e)
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
class DebitCreditAPIView(APIView):

    def get(self, request):
        query = """
        SELECT
            p.pushnotedrcrnotenumber AS "debitCreditRef",
            c.customerskrapin AS "clientPin",
            p.pushnotecode AS "uniqueRef",
            pt.transactionscode AS "transactionCode",
            t.transactionstotalamount AS "transactionTotalAmount",
            CASE
                WHEN c.customersname IS NOT NULL
                     AND TRIM(c.customersname) <> ''
                THEN c.customersname
                ELSE TRIM(
                    COALESCE(c.customersfirstname, '') || ' ' ||
                    COALESCE(c.customerssecondname, '') || ' ' ||
                    COALESCE(c.customerslastname, '')
                )
            END AS "clientName"
        FROM pushnote p
        LEFT JOIN customers c
            ON p.customerscode = c.customerscode
        LEFT JOIN pushnotetransaction pt
            ON p.pushnotecode = pt.pushnotecode
        LEFT JOIN transactions t
            ON t.transactionscode = pt.transactionscode
        """

        with connections['default_betterlife'].cursor() as cursor:
            cursor.execute(query)

            columns = [col[0] for col in cursor.description]
            results = [
                dict(zip(columns, row))
                for row in cursor.fetchall()
            ]

        return Response(results, status=status.HTTP_200_OK)
    
    



class DebitCreditListAPIView(APIView):

    def get(self, request):
        queryset = DebitCredit.objects.all().order_by("-created_at")
        serializer = DebitCreditSerializer(queryset, many=True)
        return Response(serializer.data)
    
    
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status

# from .models import DebitCredit
# from .services.etims_service import create_medical_tax_transaction


class PushToEtimsAPIView(APIView):

    def post(self, request, debit_id):
        obj = DebitCredit.objects.get(id=debit_id)

        payload = {
            "debitCreditRef": obj.debit_credit_reference,
            "clientPin": obj.client_pin,
            "clientName": obj.client_name,
            "amount": float(obj.transaction_total_amount or 0),
            "uniqueRef": str(obj.source_pushnote_code),
            "originalReference": obj.debit_credit_reference,
        }

        try:
            result = create_medical_tax_transaction(payload)

            obj.etims_status = "SENT"
            obj.save()

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            obj.etims_status = "FAILED"
            obj.kra_message = str(e)
            obj.save()

            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        
        
# from .services.etims_service import get_kra_reference


class QueryKraRefAPIView(APIView):

    def get(self, request, unique_ref):
        try:
            result = get_kra_reference(unique_ref)

            obj = DebitCredit.objects.filter(
                source_pushnote_code=unique_ref
            ).first()

            if obj:
                obj.kra_ref = result.get("ref")
                obj.kra_message = result.get("message")

                if result.get("ref"):
                    obj.etims_status = "COMPLETED"

                obj.save()

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )