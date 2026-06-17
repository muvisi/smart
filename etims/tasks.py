from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from .models import DebitCredit
from .services import create_medical_tax_transaction


@shared_task
def send_pending_transactions_task():

    pending_items = DebitCredit.objects.filter(
        Q(etims_status="PENDING") | Q(etims_status="FAILED")
    ).order_by("created_at")

    processed_count = 0
    failed_count = 0

    for obj in pending_items:

        # ⚠️ prevent duplicate processing in case of overlap
        obj.etims_status = "PROCESSING"
        obj.save()

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

            processed_count += 1

        except Exception as e:

            obj.etims_status = "FAILED"
            obj.last_error = str(e)
            obj.save()

            failed_count += 1

    return {
        "processed": processed_count,
        "failed": failed_count
    }
    
    
    
from django.db import connections

from .models import DebitCredit
from etims.services import get_kra_reference


@shared_task
def sync_kra_references_task():

    sent_items = DebitCredit.objects.filter(
        etims_status="SENT"
    ).order_by("created_at")

    processed = 0
    failed = 0

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
                        [kra_ref, obj.debit_credit_reference]
                    )

            processed += 1

        except Exception as e:
            obj.last_error = str(e)
            obj.save()
            failed += 1

    return {
        "processed": processed,
        "failed": failed
    }
    
# from celery import shared_task
from django.db import connections, transaction




@shared_task
def sync_debit_credit_notes_task():

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
    WHERE p.pushnoteetimsiskraposted IS NOT TRUE
    """

    try:
        with connections['default_betterlife'].cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        if not rows:
            return {
                "success": True,
                "message": "No new records to sync",
                "created": 0,
                "updated": 0
            }

        created_count = 0
        updated_count = 0
        processed_refs = []

        with transaction.atomic():
            for row in rows:

                debit_ref = row["debitCreditRef"]

                _, created = DebitCredit.objects.update_or_create(
                    debit_credit_reference=debit_ref,
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

                processed_refs.append(debit_ref)

        # -----------------------------------
        # Mark as posted in external DB
        # -----------------------------------
        if processed_refs:
            with connections['default_betterlife'].cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE pushnote
                    SET pushnoteetimsiskraposted = TRUE
                    WHERE pushnotedrcrnotenumber = ANY(%s)
                    """,
                    [processed_refs]
                )

        return {
            "success": True,
            "created": created_count,
            "updated": updated_count,
            "total_processed": len(rows)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }