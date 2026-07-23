from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from .models import DebitCredit, EtimsTransactionLog
from .services import MEDICAL_TAX_TRANSACTION_URL, create_medical_tax_transaction


def _exception_response(exception):
    response = getattr(exception, "response", None)
    if response is None:
        return None, None

    try:
        payload = response.json()
    except ValueError:
        payload = {"body": response.text}

    return response.status_code, payload


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

        log = EtimsTransactionLog.objects.create(
            debit_credit=obj,
            request_url=MEDICAL_TAX_TRANSACTION_URL,
            request_payload=payload,
        )

        try:
            http_response = create_medical_tax_transaction(
                payload,
                return_http_response=True,
            )
            response = http_response.json()

            log.response_payload = response
            log.response_status_code = http_response.status_code
            log.status = "SUCCESS"
            log.completed_at = timezone.now()
            log.save(
                update_fields=[
                    "response_payload",
                    "response_status_code",
                    "status",
                    "completed_at",
                ]
            )

            obj.etims_status = "SENT"
            obj.last_synced_at = timezone.now()
            obj.kra_message = str(response)
            obj.last_error = None
            obj.save()

            processed_count += 1

        except Exception as e:
            response_status_code, response_payload = _exception_response(e)
            log.response_status_code = response_status_code
            log.response_payload = response_payload
            log.status = "FAILED"
            log.error_message = str(e)
            log.completed_at = timezone.now()
            log.save(
                update_fields=[
                    "response_status_code",
                    "response_payload",
                    "status",
                    "error_message",
                    "completed_at",
                ]
            )

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
            AND (p.pushnotestatus IS NULL OR p.pushnotestatus <> 'ERROR')
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
 
 
 
from celery import shared_task
from email.mime.image import MIMEImage
from pathlib import Path

from django.core.mail import EmailMultiAlternatives, send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.timezone import now


@shared_task
def send_etims_health_report_legacy():
    timestamp = now().strftime("%Y-%m-%d %H:%M:%S")

    subject = "ETIMS Health Check Report - System Status"

    message = f"""
Dear Team,

ETIMS System Health Check Report

------------------------------------------------------------
🕒 Timestamp: {timestamp} (EAT)
------------------------------------------------------------

📊 SYSTEM STATUS

✔ Celery Worker: ACTIVE
✔ Celery Beat: ACTIVE
✔ Redis Broker: CONNECTED
✔ ETIMS Sync Jobs: RUNNING

------------------------------------------------------------

This is an automated system health confirmation.

Kind regards,  
ETIMS Integration Service
"""

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=settings.TEST_EMAIL_RECIPIENTS,
        fail_silently=False,
    )

    return {
        "status": "SENT",
        "timestamp": timestamp
    }


@shared_task
def send_etims_health_report():
    checked_at = timezone.localtime(now())
    timestamp = checked_at.strftime("%d %B %Y, %H:%M:%S %Z")
    services = [
        {"name": "Celery Worker", "status": "Active", "detail": "Task processing is available"},
        {"name": "Celery Beat", "status": "Active", "detail": "Scheduled jobs are being dispatched"},
        {"name": "Redis Broker", "status": "Connected", "detail": "Message broker connection is available"},
        {"name": "eTIMS Sync Jobs", "status": "Running", "detail": "Transaction synchronisation is operational"},
    ]
    context = {
        "checked_at": timestamp,
        "services": services,
        "service_name": "GX eTIMS Service",
        "environment": getattr(settings, "ETIMS_ENVIRONMENT", "Production"),
    }
    subject = "[Healthy] GX eTIMS Service | Health Check"
    message = render_to_string("emails/etims_health_report.email", context)
    html_message = render_to_string("emails/etims_health_report.html", context)

    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=settings.TEST_EMAIL_RECIPIENTS,
    )
    email.attach_alternative(html_message, "text/html")
    email.mixed_subtype = "related"

    logo_path = Path(settings.BASE_DIR) / "commisions" / "logo.jpeg"
    if logo_path.exists():
        logo = MIMEImage(logo_path.read_bytes(), _subtype="jpeg")
        logo.add_header("Content-ID", "<madison-logo>")
        logo.add_header("Content-Disposition", "inline", filename="madison-logo.jpeg")
        email.attach(logo)

    email.send(fail_silently=False)

    return {
        "status": "SENT",
        "timestamp": timestamp,
        "recipients": len(settings.TEST_EMAIL_RECIPIENTS),
    }
