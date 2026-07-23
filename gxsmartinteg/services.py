import logging
import time
from urllib.parse import urlencode

import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from django.conf import settings

from .models import GxSmartMemberSyncLog

logger = logging.getLogger(__name__)


GX_MEMBERS_SELECT = """
SELECT
    CONCAT('COPR/', TRIM(cm.customersmembersfamilynumber::TEXT)) AS "familyCode",
    CONCAT(
        'COPR/',
        TRIM(cm.customersmembersfamilynumber::TEXT),
        '/',
        TRIM(cm.customersmembersnumber::TEXT)
    ) AS "membershipNumber",
    COALESCE(TRIM(cm.customersmembersoldnumber::TEXT), '') AS "OldmembershipNumber",
    CONCAT(
        'COPR/',
        TRIM(cm.customersmembersfamilynumber::TEXT),
        '/',
        TRIM(cm.customersmembersnumber::TEXT)
    ) AS "staffNumber",
    COALESCE(TRIM(cm.customersmemberslastname), '') AS "surname",
    COALESCE(TRIM(cm.customersmembersfirstname), '') AS "secondName",
    COALESCE(TRIM(cm.customersmemberssecondname), '') AS "thirdName",
    '' AS "otherNames",
    '' AS "idNumber",
    COALESCE(TO_CHAR(cm.customersmembersdateofbirth, 'YYYY-MM-DD'), 'null') AS "dob",
    CASE
        WHEN cm.customersmembersgender = '1' THEN 'M'
        WHEN cm.customersmembersgender = '2' THEN 'F'
        ELSE ''
    END AS "gender",
    '' AS "nhifNumber",
    CASE
        WHEN TRIM(cm.customersmembersnumber::TEXT) = '1' THEN 'P'
        WHEN TRIM(cm.customersmembersnumber::TEXT) = '2' THEN 'S'
        ELSE 'C'
    END AS "memType",
    COALESCE(TO_CHAR(cpm.customerspolicymemberseffectiv, 'YYYY-MM-DD'), '') AS "schemeStartDate",
    COALESCE(
        TO_CHAR(
            CASE
                WHEN cpm.customerspolicymembersenddate = DATE '0001-01-01'
                    THEN cp.customerspolicyenddate
                ELSE cpm.customerspolicymembersenddate
            END,
            'YYYY-MM-DD'
        ),
        ''
    ) AS "schemeEndDate",
    CONCAT(
        TRIM(cf.customersfamilycategoriescode::TEXT),
        '-',
        TRIM(cpm.customerspolicyanniversary::TEXT)
    ) AS "clnCatCode",
    CONCAT(
        '1000',
        TRIM(cpm.customerscode::TEXT),
        TRIM(cpm.customerspolicycode::TEXT)
    ) AS "clnPolCode",
    COALESCE(TRIM(cm.customersmembersmobilenumber), '') AS "phone_number",
    COALESCE(TRIM(cm.customersmembersemail), '') AS "email_address",
    'integration.user@madison.co.ke' AS "userID",
    'KE' AS "country",
    'MIC77FB12F4D0BA1BB7AAFC53PRODKE' AS "customerid",
    'KE' AS "roamingCountries"
FROM public.customerspolicymembers cpm
INNER JOIN public.customersmembers cm
    ON cm.customerscode = cpm.customerscode
   AND cm.customersmembersfamilynumber = cpm.customersmembersfamilynumber
   AND cm.customersmemberscode = cpm.customersmemberscode
INNER JOIN public.customersfamily cf
    ON cf.customerscode = cm.customerscode
   AND cf.customersmembersfamilynumber = cm.customersmembersfamilynumber
INNER JOIN public.customerspolicy cp
    ON cp.customerscode = cpm.customerscode
   AND cp.customerspolicycode = cpm.customerspolicycode
   AND cp.customerspolicyanniversary = cpm.customerspolicyanniversary
"""


class GxSmartMemberSyncService:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.smart_token = None

    def get_betterlife_connection(self):
        database = settings.DATABASES["default_betterlife"]

        return psycopg2.connect(
            dbname=database["NAME"],
            user=database["USER"],
            password=database["PASSWORD"],
            host=database.get("HOST", "127.0.0.1"),
            port=database.get("PORT", "5432"),
        )

    def get_smart_token(self):
        params = {
            "client_id": settings.SMART_CLIENT_ID,
            "client_secret": settings.SMART_CLIENT_SECRET,
            "grant_type": settings.SMART_GRANT_TYPE,
        }

        try:
            response = self.session.post(
                f"{settings.SMART_ACCESS_TOKEN}{urlencode(params)}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            response.raise_for_status()
            return response.json().get("access_token")
        except Exception as exc:
            logger.error(f"SMART auth failed for GX member sync: {exc}")
            return None

    def fetch_one_member(
        self,
        customers_code="597",
        policy_version=2,
        policy_code=None,
        family_number=None,
        member_number=None,
        membership_number=None,
    ):
        members = self.fetch_members(
            customers_code=customers_code,
            policy_version=policy_version,
            policy_code=policy_code,
            family_number=family_number,
            member_number=member_number,
            membership_number=membership_number,
            limit=1,
        )
        return members[0] if members else None

    def fetch_members(
        self,
        customers_code="597",
        policy_version=2,
        policy_code=None,
        family_number=None,
        member_number=None,
        membership_number=None,
        limit=1000,
    ):
        where_clauses = [
            "cpm.customerscode = %s",
            "cpm.vcustomerspolicyversion = %s",
        ]
        params = [customers_code, policy_version]

        if policy_code:
            where_clauses.append("TRIM(cpm.customerspolicycode::TEXT) = %s")
            params.append(str(policy_code).strip())

        if family_number:
            where_clauses.append("TRIM(cm.customersmembersfamilynumber::TEXT) = %s")
            params.append(str(family_number).strip())

        if member_number:
            where_clauses.append("TRIM(cm.customersmembersnumber::TEXT) = %s")
            params.append(str(member_number).strip())

        if membership_number:
            where_clauses.append(
                """
                CONCAT(
                    'COPR/',
                    TRIM(cm.customersmembersfamilynumber::TEXT),
                    '/',
                    TRIM(cm.customersmembersnumber::TEXT)
                ) = %s
                """
            )
            params.append(str(membership_number).strip())

        params.append(limit)

        query = f"""
{GX_MEMBERS_SELECT}
WHERE {" AND ".join(where_clauses)}
ORDER BY
    cpm.customerspolicycode,
    cm.customersmembersfamilynumber,
    cm.customersmembersnumber
LIMIT %s
"""

        with self.get_betterlife_connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def send_member_to_smart(self, member_payload):
        http_code = 500

        try:
            smart_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(member_payload)}"
            response = self.session.post(
                smart_url,
                headers={"Authorization": f"Bearer {self.smart_token}"},
                timeout=60,
            )
            http_code = response.status_code
            try:
                response_payload = response.json()
            except ValueError:
                response_payload = {"raw": response.text}

            success = str(response_payload.get("successful")).lower() == "true"
            return success, http_code, response_payload, None
        except Exception as exc:
            return False, http_code, {"error": str(exc)}, str(exc)

    def already_sent_successfully(self, membership_number):
        return GxSmartMemberSyncLog.objects.filter(
            membership_number=membership_number,
            status=1,
            sent_to_smart=True,
        ).exists()

    def sync_single_member(
        self,
        customers_code="597",
        policy_version=2,
        policy_code=None,
        family_number=None,
        member_number=None,
        membership_number=None,
    ):
        member_payload = self.fetch_one_member(
            customers_code=customers_code,
            policy_version=policy_version,
            policy_code=policy_code,
            family_number=family_number,
            member_number=member_number,
            membership_number=membership_number,
        )

        if not member_payload:
            return {"status": "error", "message": "No matching GX member found."}

        membership_number = member_payload.get("membershipNumber")
        if self.already_sent_successfully(membership_number):
            log = self.create_log(
                member_payload=member_payload,
                response_payload={
                    "message": "Member already successfully sent to SMART. Skipped duplicate send."
                },
                http_code=200,
                status=3,
                sent_to_smart=False,
                error_message="Duplicate successful SMART sync skipped",
            )
            return {
                "status": "skipped",
                "message": "Member already successfully sent to SMART. Not sent again.",
                "log_id": str(log.id),
                "payload": member_payload,
            }

        self.smart_token = self.get_smart_token()
        if not self.smart_token:
            log = self.create_log(
                member_payload=member_payload,
                response_payload={"error": "Failed to get SMART token"},
                http_code=400,
                status=2,
                sent_to_smart=False,
                error_message="Failed to get SMART token",
            )
            return {
                "status": "failed",
                "message": "Failed to get SMART token.",
                "log_id": str(log.id),
            }

        success, http_code, response_payload, error_message = self.send_member_to_smart(
            member_payload
        )
        log = self.create_log(
            member_payload=member_payload,
            response_payload=response_payload,
            http_code=http_code,
            status=1 if success else 2,
            sent_to_smart=True,
            error_message=error_message,
        )

        return {
            "status": "success" if success else "failed",
            "log_id": str(log.id),
            "http_code": http_code,
            "payload": member_payload,
            "smart_response": response_payload,
        }

    def sync_members_batch(
        self,
        customers_code="6571",
        policy_version=1,
        policy_code=None,
        limit=1000,
        target_duration_seconds=120,
    ):
        members = self.fetch_members(
            customers_code=customers_code,
            policy_version=policy_version,
            policy_code=policy_code,
            limit=limit,
        )

        if not members:
            return {
                "status": "error",
                "message": "No matching GX members found.",
                "total_fetched": 0,
            }

        stats = {
            "total_fetched": len(members),
            "sent": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }
        logs = []
        start_time = time.monotonic()
        send_interval = target_duration_seconds / max(len(members), 1)
        next_send_time = start_time

        pending_members = []
        for member_payload in members:
            membership_number = member_payload.get("membershipNumber")
            if self.already_sent_successfully(membership_number):
                log = self.create_log(
                    member_payload=member_payload,
                    response_payload={
                        "message": "Member already successfully sent to SMART. Skipped duplicate send."
                    },
                    http_code=200,
                    status=3,
                    sent_to_smart=False,
                    error_message="Duplicate successful SMART sync skipped",
                )
                stats["skipped"] += 1
                logs.append(
                    {
                        "membershipNumber": membership_number,
                        "status": "skipped",
                        "log_id": str(log.id),
                    }
                )
            else:
                pending_members.append(member_payload)

        if pending_members:
            self.smart_token = self.get_smart_token()
            if not self.smart_token:
                for member_payload in pending_members:
                    log = self.create_log(
                        member_payload=member_payload,
                        response_payload={"error": "Failed to get SMART token"},
                        http_code=400,
                        status=2,
                        sent_to_smart=False,
                        error_message="Failed to get SMART token",
                    )
                    stats["failed"] += 1
                    logs.append(
                        {
                            "membershipNumber": member_payload.get("membershipNumber"),
                            "status": "failed",
                            "log_id": str(log.id),
                        }
                    )

                return {
                    "status": "failed",
                    "message": "Failed to get SMART token.",
                    "stats": stats,
                    "logs": logs,
                }

        for member_payload in pending_members:
            wait_seconds = next_send_time - time.monotonic()
            if wait_seconds > 0:
                time.sleep(wait_seconds)

            success, http_code, response_payload, error_message = self.send_member_to_smart(
                member_payload
            )
            log = self.create_log(
                member_payload=member_payload,
                response_payload=response_payload,
                http_code=http_code,
                status=1 if success else 2,
                sent_to_smart=True,
                error_message=error_message,
            )

            stats["sent"] += 1
            if success:
                stats["success"] += 1
                log_status = "success"
            else:
                stats["failed"] += 1
                log_status = "failed"

            logs.append(
                {
                    "membershipNumber": member_payload.get("membershipNumber"),
                    "status": log_status,
                    "http_code": http_code,
                    "log_id": str(log.id),
                }
            )
            next_send_time += send_interval

        elapsed_seconds = round(time.monotonic() - start_time, 2)

        return {
            "status": "success" if stats["failed"] == 0 else "completed_with_failures",
            "customers_code": customers_code,
            "policy_code": policy_code,
            "policy_version": policy_version,
            "limit": limit,
            "target_duration_seconds": target_duration_seconds,
            "elapsed_seconds": elapsed_seconds,
            "stats": stats,
            "logs": logs,
        }

    def create_log(
        self,
        member_payload,
        response_payload,
        http_code,
        status,
        sent_to_smart,
        error_message=None,
    ):
        return GxSmartMemberSyncLog.objects.create(
            family_code=member_payload.get("familyCode"),
            membership_number=member_payload.get("membershipNumber"),
            old_membership_number=member_payload.get("OldmembershipNumber"),
            request_object=member_payload,
            response_object=response_payload,
            status=status,
            sent_to_smart=sent_to_smart,
            http_code=http_code,
            error_message=error_message,
        )
