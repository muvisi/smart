import psycopg2
from psycopg2.extras import RealDictCursor
from django.conf import settings
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import GxSmartMemberSyncService


MEMBERS_QUERY = """
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
WHERE cpm.customerscode = %s
  AND cpm.vcustomerspolicyversion = %s
ORDER BY
    cpm.customerspolicycode,
    cm.customersmembersfamilynumber,
    cm.customersmembersnumber
LIMIT %s
"""


class BetterlifeMembersAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get_betterlife_connection(self):
        database = settings.DATABASES["default_betterlife"]

        return psycopg2.connect(
            dbname=database["NAME"],
            user=database["USER"],
            password=database["PASSWORD"],
            host=database.get("HOST", "127.0.0.1"),
            port=database.get("PORT", "5432"),
        )

    def get(self, request, *args, **kwargs):
        customers_code = request.query_params.get("customers_code", "582")
        policy_version = request.query_params.get("policy_version", "1")
        limit = request.query_params.get("limit", "1500")

        try:
            policy_version = int(policy_version)
            limit = min(int(limit), 1500)
        except ValueError:
            return Response(
                {"error": "policy_version and limit must be valid numbers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if limit < 1:
            return Response(
                {"error": "limit must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with self.get_betterlife_connection() as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(MEMBERS_QUERY, [customers_code, policy_version, limit])
                    members = [dict(row) for row in cursor.fetchall()]
        except psycopg2.Error as exc:
            return Response(
                {"error": f"Failed to fetch Betterlife members: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "count": len(members),
                "customers_code": customers_code,
                "policy_version": policy_version,
                "results": members,
            },
            status=status.HTTP_200_OK,
        )


class GxSmartMemberSyncAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, customers_code=None, policy_version=None, *args, **kwargs):
        customers_code = customers_code or request.query_params.get("customers_code", "582")
        policy_code = request.query_params.get("policy_code")
        policy_version = policy_version or request.query_params.get("policy_version", "1")
        limit = request.query_params.get("limit", "1500")
        target_duration_seconds = request.query_params.get("target_duration_seconds", "120")

        try:
            policy_version = int(policy_version)
            limit = min(int(limit), 1500)
            target_duration_seconds = min(int(target_duration_seconds), 180)
        except ValueError:
            return Response(
                {
                    "error": "policy_version, limit, and target_duration_seconds must be valid numbers."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if limit < 1:
            return Response(
                {"error": "limit must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if target_duration_seconds < 1:
            return Response(
                {"error": "target_duration_seconds must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = GxSmartMemberSyncService()
        if (
            request.query_params.get("family_number")
            or request.query_params.get("member_number")
            or request.query_params.get("membership_number")
        ):
            result = service.sync_single_member(
                customers_code=customers_code,
                policy_version=policy_version,
                policy_code=policy_code,
                family_number=request.query_params.get("family_number"),
                member_number=request.query_params.get("member_number"),
                membership_number=request.query_params.get("membership_number"),
            )
        else:
            result = service.sync_members_batch(
                customers_code=customers_code,
                policy_version=policy_version,
                policy_code=policy_code,
                limit=limit,
                target_duration_seconds=target_duration_seconds,
            )

        response_status = (
            status.HTTP_200_OK
            if result.get("status")
            in ["success", "failed", "skipped", "completed_with_failures"]
            else status.HTTP_404_NOT_FOUND
        )
        return Response(result, status=response_status)
