
from django.db import connections
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class CommissionFinancialViewPaid(APIView):
    """Returns only commissions marked as paid (commission_paid = 1)."""

    valid_filters = {
        "push_note_code": "sub.push_note_code",
        "policy_number": "sub.policy_number",
        "transaction_number": "sub.transaction_number",
        "intermediary_name": "sub.intermediary_name",
        "broker_name": "sub.broker_name",
        "payment_status": "sub.payment_status",
        "customer_name": "sub.customer_name",
        "debit_code": "sub.debit_code",
        "paid_at": "sub.paid_at",
    }

    def get(self, request):
        where_clauses = ["sub.commission_paid = 1"]
        params = []

        # Apply optional filters
        for param, col in self.valid_filters.items():
            val = request.query_params.get(param)

            if val:
                if param == "paid_at":
                    where_clauses.append(
                        "LEFT(sub.paid_at, 10) = %s"
                    )
                    params.append(val)
                else:
                    where_clauses.append(f"{col}::text ILIKE %s")
                    params.append(f"%{val}%")

        # Date range filters
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        if start_date and end_date:
            where_clauses.append(
                "LEFT(sub.paid_at, 10) BETWEEN %s AND %s"
            )
            params.extend([start_date, end_date])

        elif start_date:
            where_clauses.append(
                "LEFT(sub.paid_at, 10) >= %s"
            )
            params.append(start_date)

        elif end_date:
            where_clauses.append(
                "LEFT(sub.paid_at, 10) <= %s"
            )
            params.append(end_date)

        where_sql = "WHERE " + " AND ".join(where_clauses)

        query = f"""
            SELECT
                sub.push_note_code,
                sub.push_note_request_date,
                sub.policy_number,
                sub.transaction_number,
                sub.agent_code,
                sub.customer_code,
                sub.intermediary_name,
                sub.broker_name,
                sub.receipted_amount,
                sub.levies,
                sub.available_allocation,

                ROUND(
                    sub.available_allocation *
                    (sub.intermediarycommisionrate / 100),
                    2
                ) AS broker_commission,

                ROUND(
                    sub.available_allocation *
                    (sub.intermediarycommisionrate / 100) *
                    (sub.intermediarywithholdingtax / 100),
                    2
                ) AS withholding_tax,

                ROUND(
                    (
                        sub.available_allocation *
                        (sub.intermediarycommisionrate / 100)
                    ) -
                    (
                        sub.available_allocation *
                        (sub.intermediarycommisionrate / 100) *
                        (sub.intermediarywithholdingtax / 100)
                    ),
                    2
                ) AS commission_payable,

                sub.transaction_total_amount,
                sub.payment_status,
                sub.primarybenefitname,
                sub.customerspolicycode,
                sub.primarybenefitcode,
                sub.customer_name,
                sub.debit_code,
                sub.paid_by,
                sub.commission_paid,
                sub.paid_at,

                'PAID' AS commission_status

            FROM (
                SELECT
                    p.pushnotecode AS push_note_code,
                    p.pushnotereqdatetime AS push_note_request_date,
                    p.pushnotepolicynumber AS policy_number,
                    t.transactionsnumber AS transaction_number,
                    p.pushnoteagentcode AS agent_code,
                    p.customerscode AS customer_code,
                    t.transactionstotalamount AS transaction_total_amount,

                    i.intermediaryname AS intermediary_name,
                    i.intermediarycommisionrate,
                    i.intermediarywithholdingtax,

                    cus.customernamebytype AS customer_name,
                    p.pushnotedrcrnotenumber AS debit_code,

                    c.customerspolicyagentbrokername AS broker_name,

                    COALESCE(
                        sp_sum.receipted_amount, 0
                    ) AS receipted_amount,

                    ROUND(
                        (
                            COALESCE(
                                sp_sum.receipted_amount, 0
                            ) * 0.45 / 100
                        ) + 40,
                        2
                    ) AS levies,

                    ROUND(
                        COALESCE(
                            sp_sum.receipted_amount, 0
                        ) -
                        (
                            (
                                COALESCE(
                                    sp_sum.receipted_amount, 0
                                ) * 0.45 / 100
                            ) + 40
                        ),
                        2
                    ) AS available_allocation,

                    CASE
                        WHEN t.transactionstotalamount IS NULL
                            THEN 'Unknown'

                        WHEN COALESCE(
                            sp_sum.receipted_amount, 0
                        ) <= 0
                            THEN 'Unpaid'

                        WHEN t.transactionstotalamount >
                             COALESCE(
                                 sp_sum.receipted_amount, 0
                             ) + 1
                            THEN 'Partially Paid'

                        ELSE 'Fully Paid'
                    END AS payment_status,

                    p2.primarybenefitname,
                    p.customerspolicycode,
                    p2.primarybenefitcode,
                    p.paid_by,
                    p.commission_paid,

                    TO_CHAR(
                        p.paid_at,
                        'YYYY-MM-DD HH24:MI:SS'
                    ) AS paid_at

                FROM pushnote p

                LEFT JOIN transactions t
                    ON p.pushnotecode = t.transactionsnumber

                JOIN intermediary i
                    ON p.pushnoteagentcode = i.intermediarycode

                JOIN customerspolicy c
                    ON p.pushnotepolicynumber =
                       c.customerspolicynumber

                JOIN customers cus
                    ON p.customerscode = cus.customerscode

                LEFT JOIN (
                    SELECT
                        sap_payment_drcrno,
                        SUM(
                            sap_payment_allocateamount
                        ) AS receipted_amount
                    FROM sap_payment
                    GROUP BY sap_payment_drcrno
                ) sp_sum
                    ON p.pushnotedrcrnotenumber =
                       sp_sum.sap_payment_drcrno

                JOIN primarybenefit p2
                    ON p.customerspolicycode =
                       p2.primarybenefitcode

                -- Mandatory commission-paid condition
                WHERE p.commission_paid = 1

            ) sub

            {where_sql}

            ORDER BY sub.paid_at DESC NULLS LAST
        """

        try:
            with connections["default_betterlife"].cursor() as cursor:
                cursor.execute(query, params)

                columns = [
                    col[0] for col in cursor.description
                ]

                results = [
                    dict(zip(columns, row))
                    for row in cursor.fetchall()
                ]

            return Response({
                "success": True,
                "pagination": {
                    "count": len(results),
                    "next": None,
                    "previous": None,
                },
                "results": results
            }, status=status.HTTP_200_OK)

        except Exception:
            # Log the exception on the server rather than
            # exposing internal database errors to clients.
            import logging
            logging.getLogger(__name__).exception(
                "Failed to retrieve paid commissions"
            )

            return Response({
                "success": False,
                "error": "Unable to retrieve paid commissions."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
