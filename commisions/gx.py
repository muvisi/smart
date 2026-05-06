from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import connections
from rest_framework.pagination import PageNumberPagination

from commisions.models import CommissionRecord
from .serializers import CommissionRecordSerializer, DetailedCommissionRecordSerializer, AgentBrokerSerializer

# Create your views here.

class CommissionRecordsView(APIView):
    """ Returns commission records from the default_betterlife database using raw SQL. """
    
    valid_filters = {
        'push_note_code': 'p.pushnotecode',
        'push_note_request_date': 'p.pushnotereqdatetime',
        'commission_amount': 'p.pushnotecommission',
        'dr_cr_note_number': 'p.pushnotedrcrnotenumber',
        'policy_number': 'p.pushnotepolicynumber',
        'transaction_number': 't.transactionsnumber',
        'agent_code': 'p.pushnoteagentcode',
        'customer_code': 'p.customerscode',
        'transaction_total_amount': 't.transactionstotalamount',
        'intermediary_name': 'i.intermediaryname',
        'broker_name': 'c.customerspolicyagentbrokername',
        'intermediary_commission_rate': 'i.intermediarycommisionrate',
        'intermediary_with_holding_tax_rate': 'i.intermediarywithholdingtax'
    }

    def get(self, request):
        where_clauses = []
        params = []

        # 1. Partial Match Filters ( mimicking filterset_fields with icontains )
        # for param, col in self.valid_filters.items():
        #     val = request.query_params.get(param)
        #     if val:
        #         if param == 'push_note_request_date':
        #             where_clauses.append("DATE(p.pushnotereqdatetime) = %s")
        #             params.append(val)
        #         else:
        #             where_clauses.append(f"{col}::text ILIKE %s")
        #             params.append(f"%{val}%")
        
        # 1. Exact Match Filter
        for param, col in self.valid_filters.items():
            val = request.query_params.get(param)
            if val:
                if param == 'push_note_request_date':
                    where_clauses.append("DATE(p.pushnotereqdatetime) = %s")
                    params.append(val)
                else:
                    where_clauses.append(f"{col}::text = %s")
                    params.append(val)

        # Handle explicit date range
        start_date = request.query_params.get('start_date')
        if start_date:
            where_clauses.append("DATE(p.pushnotereqdatetime) >= %s")
            params.append(start_date)

        end_date = request.query_params.get('end_date')
        if end_date:
            where_clauses.append("DATE(p.pushnotereqdatetime) <= %s")
            params.append(end_date)

        # 2. Global Search Filter ( applying to all fields )
        search = request.query_params.get('search')
        if search:
            search_cols = list(self.valid_filters.values())
            search_clause = " OR ".join([f"{col}::text ILIKE %s" for col in search_cols])
            where_clauses.append(f"({search_clause})")
            params.extend([f"%{search}%"] * len(search_cols))

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # 3. Base Query
        # We wrap in a subquery so we can order the final results without violating DISTINCT ON constraints
        query = f"""
            SELECT * FROM (
                SELECT DISTINCT ON (p.pushnotecode, p.customerscode)
                    p.pushnotecode                AS push_note_code,
                    p.pushnotereqdatetime         AS push_note_request_date,
                    p.pushnotecommission          AS commission_amount,
                    p.pushnotedrcrnotenumber      AS dr_cr_note_number,
                    p.pushnotepolicynumber        AS policy_number,
                    t.transactionsnumber          AS transaction_number,
                    p.pushnoteagentcode           AS agent_code,
                    p.customerscode               AS customer_code,
                    t.transactionstotalamount     AS transaction_total_amount,
                    i.intermediaryname            AS intermediary_name,
                    c.customerspolicyagentbrokername AS broker_name,
                    i.intermediarycommisionrate           AS intermediary_commission_rate,
                    i.intermediarywithholdingtax            AS intermediary_with_holding_tax_rate
                FROM pushnote p
                LEFT JOIN transactions t
                    ON p.pushnotecode = t.transactionsnumber
                JOIN intermediary i
                    ON p.pushnoteagentcode = i.intermediarycode
                JOIN customerspolicy c
                    ON p.customerscode = c.customerscode
                WHERE i.intermediaryname <> 'DIRECT'
                ORDER BY
                    p.pushnotecode,
                    p.customerscode
            ) AS subquery
        """

        # 4. Ordering ( mimicking ordering parameters )
        outer_order = ""
        req_order = request.query_params.get('ordering')
        if req_order:
            desc = req_order.startswith('-')
            field = req_order.lstrip('-')
            if field in self.valid_filters:
                outer_order = f"ORDER BY {field} {'DESC' if desc else 'ASC'}"
        
        final_query = f"{query} {outer_order}"

        try:
            with connections['default_betterlife'].cursor() as cursor:
                cursor.execute(final_query, params)
                columns = [col[0] for col in cursor.description]
                results = [
                    dict(zip(columns, row))
                    for row in cursor.fetchall()
                ]

            # Allow bypassing pagination for full data export
            if request.query_params.get('paginate', '').lower() == 'false' or request.query_params.get('export', '').lower() == 'true':
                serializer = CommissionRecordSerializer(results, many=True)
                return Response(serializer.data)

            paginator = PageNumberPagination()
            paginated_results = paginator.paginate_queryset(results, request, view=self)
            
            serializer = CommissionRecordSerializer(paginated_results, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DetailedCommissionRecordsView(APIView):
    """ Returns detailed commission records including receipt information and payment statuses. """

    valid_filters = {
        'push_note_code': 'p.pushnotecode',
        'push_note_request_date': 'p.pushnotereqdatetime',
        'commission_amount': 'p.pushnotecommission',
        'dr_cr_note_number': 'p.pushnotedrcrnotenumber',
        'policy_number': 'p.pushnotepolicynumber',
        'transaction_number': 't.transactionsnumber',
        'agent_code': 'p.pushnoteagentcode',
        'customer_code': 'p.customerscode',
        'transaction_total_amount': 't.transactionstotalamount',
        'intermediary_name': 'i.intermediaryname',
        'broker_name': 'c.customerspolicyagentbrokername',
        'intermediary_commission_rate': 'i.intermediarycommisionrate',
        'intermediary_with_holding_tax_rate': 'i.intermediarywithholdingtax',
        'receipted_amount': 'sp_sum.receipted_amount',
        'payment_status': 'payment_status',
        'primarybenefitname': 'p2.primarybenefitname',
        'customerspolicycode': 'p.customerspolicycode',
        'primarybenefitcode': 'p2.primarybenefitcode'
    }

    def get(self, request):
        where_clauses = ["i.intermediaryname <> 'DIRECT'"]
        params = []

       
        for param, col in self.valid_filters.items():
            val = request.query_params.get(param)
            if val:
                if param == 'push_note_request_date':
                    where_clauses.append("DATE(p.pushnotereqdatetime) = %s")
                    params.append(val)
                elif param == 'payment_status':
                    # To filter by the CASE status exactly
                    where_clauses.append(f"CASE WHEN t.transactionstotalamount > sp_sum.receipted_amount + 1 THEN 'Partially Paid' ELSE 'Fully Paid' END = %s")
                    params.append(val)
                else:
                    where_clauses.append(f"{col}::text = %s")
                    params.append(val)

        # Handle explicit date range
        start_date = request.query_params.get('start_date')
        if start_date:
            where_clauses.append("DATE(p.pushnotereqdatetime) >= %s")
            params.append(start_date)

        end_date = request.query_params.get('end_date')
        if end_date:
            where_clauses.append("DATE(p.pushnotereqdatetime) <= %s")
            params.append(end_date)

        # 2. Global Search Filter
        search = request.query_params.get('search')
        if search:
            search_cols = list(self.valid_filters.values())
            # Replace payment_status alias for the WHERE clause
            search_cols = [c if c != 'payment_status' else "CASE WHEN t.transactionstotalamount > sp_sum.receipted_amount + 1 THEN 'Partially Paid' ELSE 'Fully Paid' END" for c in search_cols]
            search_clause = " OR ".join([f"{col}::text ILIKE %s" for col in search_cols])
            where_clauses.append(f"({search_clause})")
            params.extend([f"%{search}%"] * len(search_cols))

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # 3. Base Query
        query = f"""
            SELECT * FROM (
                SELECT
                    p.pushnotecode                AS push_note_code,
                    p.pushnotereqdatetime         AS push_note_request_date,
                    p.pushnotecommission          AS commission_amount,
                    p.pushnotedrcrnotenumber      AS dr_cr_note_number,
                    p.pushnotepolicynumber        AS policy_number,
                    t.transactionsnumber          AS transaction_number,
                    p.pushnoteagentcode           AS agent_code,
                    p.customerscode               AS customer_code,
                    t.transactionstotalamount     AS transaction_total_amount,
                    i.intermediaryname            AS intermediary_name,
                    c.customerspolicyagentbrokername AS broker_name,
                    i.intermediarycommisionrate   AS intermediary_commission_rate,
                    i.intermediarywithholdingtax  AS intermediary_with_holding_tax_rate,
                    sp_sum.receipted_amount,
                    CASE
                        WHEN t.transactionstotalamount > sp_sum.receipted_amount + 1
                            THEN 'Partially Paid'
                        ELSE 'Fully Paid'
                    END AS payment_status,
                    p2.primarybenefitname,
                    p.customerspolicycode,
                    p2.primarybenefitcode
                FROM pushnote p
                LEFT JOIN transactions t
                    ON p.pushnotecode = t.transactionsnumber
                JOIN intermediary i
                    ON p.pushnoteagentcode = i.intermediarycode
                JOIN customerspolicy c
                    ON p.customerscode = c.customerscode
                JOIN (
                    SELECT
                        sap_payment_drcrno,
                        SUM(sap_payment_allocateamount) AS receipted_amount
                    FROM sap_payment
                    GROUP BY sap_payment_drcrno
                ) sp_sum
                    ON p.pushnotedrcrnotenumber = sp_sum.sap_payment_drcrno
                JOIN primarybenefit p2
                    ON p.customerspolicycode = p2.primarybenefitcode
                {where_sql}
            ) AS subquery
        """

        # 4. Ordering
        outer_order = ""
        req_order = request.query_params.get('ordering')
        if req_order:
            desc = req_order.startswith('-')
            field = req_order.lstrip('-')
            if field in self.valid_filters:
                outer_order = f"ORDER BY {field} {'DESC' if desc else 'ASC'}"

        final_query = f"{query} {outer_order}"

        try:
            with connections['default_betterlife'].cursor() as cursor:
                cursor.execute(final_query, params)
                columns = [col[0] for col in cursor.description]
                results = [
                    dict(zip(columns, row))
                    for row in cursor.fetchall()
                ]

            if request.query_params.get('paginate', '').lower() == 'false' or request.query_params.get('export', '').lower() == 'true':
                serializer = DetailedCommissionRecordSerializer(results, many=True)
                return Response(serializer.data)

            paginator = PageNumberPagination()
            paginated_results = paginator.paginate_queryset(results, request, view=self)

            serializer = DetailedCommissionRecordSerializer(paginated_results, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import connections
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import connections
from rest_framework.pagination import PageNumberPagination


class CommissionFinancialView(APIView):
    """Returns commission financial breakdown with allocation, broker commission, and withholding tax."""

    valid_filters = {
        "push_note_code": "sub.push_note_code",
        "policy_number": "sub.policy_number",
        "transaction_number": "sub.transaction_number",
        "intermediary_name": "sub.intermediary_name",
        "broker_name": "sub.broker_name",
        "payment_status": "sub.payment_status",
        "customer_name": "sub.customer_name",
        "debit_code": "sub.debit_code",
    }

    def get(self, request):

        # ✅ FIXED: use ONLY sub.*
        where_clauses = [
            "sub.intermediary_name <> 'DIRECT'",
            "sub.receipted_amount > 5"
        ]
        params = []

        # 🔍 filters
        for param, col in self.valid_filters.items():
            val = request.query_params.get(param)
            if val:
                where_clauses.append(f"{col}::text ILIKE %s")
                params.append(f"%{val}%")

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

                ROUND(sub.available_allocation * 0.10, 2) AS broker_commission,
                ROUND(sub.available_allocation * 0.10 * 0.10, 2) AS withholding_tax,
                ROUND(
                    (sub.available_allocation * 0.10) -
                    (sub.available_allocation * 0.10 * 0.10),
                2) AS commission_payable,

                sub.transaction_total_amount,
                sub.payment_status,

                sub.primarybenefitname,
                sub.customerspolicycode,
                sub.primarybenefitcode,
                sub.customer_name,
                sub.debit_code

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
                    c.customerspolicyagentbrokername AS broker_name,
                    cus.customernamebytype AS customer_name,
                    p.pushnotedrcrnotenumber AS debit_code,

                    COALESCE(sp_sum.receipted_amount, 0) AS receipted_amount,

                    ROUND(
                        (COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40,
                    2) AS levies,

                    ROUND(
                        COALESCE(sp_sum.receipted_amount, 0) -
                        ((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40),
                    2) AS available_allocation,

                    CASE
                        WHEN t.transactionstotalamount >
                             COALESCE(sp_sum.receipted_amount, 0) + 1
                            THEN 'Partially Paid'
                        ELSE 'Fully Paid'
                    END AS payment_status,

                    p2.primarybenefitname,
                    p.customerspolicycode,
                    p2.primarybenefitcode

                FROM pushnote p

                LEFT JOIN transactions t
                    ON p.pushnotecode = t.transactionsnumber

                JOIN intermediary i
                    ON p.pushnoteagentcode = i.intermediarycode

                JOIN customerspolicy c
                    ON p.customerscode = c.customerscode
                    
                JOIN customers cus
                ON p.customerscode = cus.customerscode    

                LEFT JOIN (
                    SELECT
                        sap_payment_drcrno,
                        SUM(sap_payment_allocateamount) AS receipted_amount
                    FROM sap_payment
                    GROUP BY sap_payment_drcrno
                ) sp_sum
                    ON p.pushnotedrcrnotenumber = sp_sum.sap_payment_drcrno

                JOIN primarybenefit p2
                    ON p.customerspolicycode = p2.primarybenefitcode

                WHERE i.intermediaryname <> 'DIRECT'
            ) sub

            {where_sql}
        """

        try:
            with connections['default_betterlife'].cursor() as cursor:
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]

            # 🔄 optional no pagination
            if request.query_params.get('paginate', '').lower() == 'false':
                return Response(results)

            paginator = PageNumberPagination()
            paginated = paginator.paginate_queryset(results, request, view=self)

            return paginator.get_paginated_response(paginated)

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
            
            
from rest_framework.response import Response
from rest_framework import status
from django.db import connections
from rest_framework.pagination import PageNumberPagination


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import connections
from rest_framework.pagination import PageNumberPagination
from decimal import Decimal
from django.db import connections, transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination

# from your_app.models import CommissionRecord
class CommissionFinancialViewPayable(APIView):
    """Returns commission financial breakdown + syncs to DB (atomic bulk upsert)."""

    valid_filters = {
        "push_note_code": "sub.push_note_code",
        "policy_number": "sub.policy_number",
        "transaction_number": "sub.transaction_number",
        "intermediary_name": "sub.intermediary_name",
        "broker_name": "sub.broker_name",
        "payment_status": "sub.payment_status",
        "customer_name": "sub.customer_name",
        "debit_code": "sub.debit_code",
    }

    def get(self, request):

        where_clauses = [
            "sub.intermediary_name <> 'DIRECT'",
            "sub.receipted_amount > 5",
            "sub.payment_status = 'Fully Paid'"  # ✅ ADDED FILTER
        ]
        params = []

        for param, col in self.valid_filters.items():
            val = request.query_params.get(param)
            if val:
                where_clauses.append(f"{col}::text ILIKE %s")
                params.append(f"%{val}%")

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

    -- ✅ UPDATED: dynamic commission
    ROUND(
        sub.available_allocation * (sub.intermediarycommisionrate / 100),
    2) AS broker_commission,

    -- ✅ UPDATED: dynamic withholding tax
    ROUND(
        sub.available_allocation * (sub.intermediarycommisionrate / 100) *
        (sub.intermediarywithholdingtax / 100),
    2) AS withholding_tax,

    -- ✅ UPDATED: dynamic commission payable
    ROUND(
        (sub.available_allocation * (sub.intermediarycommisionrate / 100)) -
        (
            sub.available_allocation * (sub.intermediarycommisionrate / 100) *
            (sub.intermediarywithholdingtax / 100)
        ),
    2) AS commission_payable,

    sub.transaction_total_amount,
    sub.payment_status,
    sub.primarybenefitname,
    sub.customerspolicycode,
    sub.primarybenefitcode,
    sub.customer_name,
    sub.debit_code

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

        -- ✅ ADDED: bring rates into subquery
        i.intermediarycommisionrate,
        i.intermediarywithholdingtax,

        cus.customernamebytype AS customer_name,
        p.pushnotedrcrnotenumber AS debit_code,

        c.customerspolicyagentbrokername AS broker_name,

        COALESCE(sp_sum.receipted_amount, 0) AS receipted_amount,

        ROUND(
            (COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40,
        2) AS levies,

        ROUND(
            COALESCE(sp_sum.receipted_amount, 0) -
            ((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40),
        2) AS available_allocation,

        CASE
            WHEN t.transactionstotalamount >
                 COALESCE(sp_sum.receipted_amount, 0) + 1
                THEN 'Partially Paid'
            ELSE 'Fully Paid'
        END AS payment_status,

        p2.primarybenefitname,
        p.customerspolicycode,
        p2.primarybenefitcode

    FROM pushnote p

    LEFT JOIN transactions t
        ON p.pushnotecode = t.transactionsnumber

    JOIN intermediary i
        ON p.pushnoteagentcode = i.intermediarycode

    JOIN customerspolicy c
        ON p.customerscode = c.customerscode

    JOIN customers cus
        ON p.customerscode = cus.customerscode    

    LEFT JOIN (
        SELECT
            sap_payment_drcrno,
            SUM(sap_payment_allocateamount) AS receipted_amount
        FROM sap_payment
        GROUP BY sap_payment_drcrno
    ) sp_sum
        ON p.pushnotedrcrnotenumber = sp_sum.sap_payment_drcrno

    JOIN primarybenefit p2
        ON p.customerspolicycode = p2.primarybenefitcode

) sub
        
        {where_sql}
        """

        try:
            with connections['default_betterlife'].cursor() as cursor:
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]

            decimal_fields = [
                "receipted_amount", "levies", "available_allocation",
                "broker_commission", "withholding_tax",
                "commission_payable", "transaction_total_amount"
            ]

            text_fields = [
                "intermediary_name", "broker_name", "primarybenefitname"
            ]

            for row in results:
                for f in text_fields:
                    if row.get(f):
                        row[f] = row[f].strip()

                for f in decimal_fields:
                    if row.get(f) is not None:
                        row[f] = Decimal(str(row[f]))

            with transaction.atomic():
                push_codes = [r["push_note_code"] for r in results if r.get("push_note_code")]

                existing_qs = CommissionRecord.objects.select_for_update().filter(
                    push_note_code__in=push_codes
                )
                existing_map = {obj.push_note_code: obj for obj in existing_qs}

                to_create = []
                to_update = []

                update_fields = [
                    "push_note_request_date",
                    "policy_number",
                    "transaction_number",
                    "agent_code",
                    "customer_code",
                    "intermediary_name",
                    "broker_name",
                    "receipted_amount",
                    "levies",
                    "available_allocation",
                    "broker_commission",
                    "withholding_tax",
                    "commission_payable",
                    "transaction_total_amount",
                    "payment_status",
                    "primarybenefitname",
                    "customerspolicycode",
                    "primarybenefitcode",
                    "customer_name",
                    "debit_code"
                ]

                for row in results:
                    code = row.get("push_note_code")
                    existing = existing_map.get(code)

                    if not existing:
                        to_create.append(CommissionRecord(**row))
                        continue

                    changed = False
                    for field in update_fields:
                        if getattr(existing, field) != row.get(field):
                            setattr(existing, field, row.get(field))
                            changed = True

                    if changed:
                        to_update.append(existing)

                if to_create:
                    CommissionRecord.objects.bulk_create(to_create, batch_size=500)

                if to_update:
                    CommissionRecord.objects.bulk_update(to_update, update_fields, batch_size=500)

            summary = {
                "created": len(to_create),
                "updated": len(to_update),
                "skipped": len(results) - len(to_create) - len(to_update),
                "total": len(results),
            }

            if request.query_params.get('paginate', '').lower() == 'false':
                return Response({
                    "success": True,
                    "summary": summary,
                    "data": results
                })

            paginator = PageNumberPagination()
            paginated = paginator.paginate_queryset(results, request, view=self)

            return Response({
                "success": True,
                "summary": summary,
                "pagination": {
                    "count": paginator.page.paginator.count,
                    "next": paginator.get_next_link(),
                    "previous": paginator.get_previous_link(),
                },
                "results": paginated
            })

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
# SELECT
#             sub.push_note_code,
#             sub.push_note_request_date,
#             sub.policy_number,
#             sub.transaction_number,
#             sub.agent_code,
#             sub.customer_code,
#             sub.intermediary_name,
#             sub.broker_name,
#             sub.receipted_amount,
#             sub.levies,
#             sub.available_allocation,
#             ROUND(sub.available_allocation * 0.10, 2) AS broker_commission,
#             ROUND(sub.available_allocation * 0.10 * 0.10, 2) AS withholding_tax,
#             ROUND(
#                 (sub.available_allocation * 0.10) -
#                 (sub.available_allocation * 0.10 * 0.10),
#             2) AS commission_payable,
#             sub.transaction_total_amount,
#             sub.payment_status,
#             sub.primarybenefitname,
#             sub.customerspolicycode,
#             sub.primarybenefitcode,
#             sub.customer_name,
#             sub.debit_code
#         FROM (
#             SELECT
#                 p.pushnotecode AS push_note_code,
#                 p.pushnotereqdatetime AS push_note_request_date,
#                 p.pushnotepolicynumber AS policy_number,
#                 t.transactionsnumber AS transaction_number,
#                 p.pushnoteagentcode AS agent_code,
#                 p.customerscode AS customer_code,
#                 t.transactionstotalamount AS transaction_total_amount,
#                 i.intermediaryname AS intermediary_name,
#                 cus.customernamebytype AS customer_name,
#                 p.pushnotedrcrnotenumber AS debit_code,

#                 c.customerspolicyagentbrokername AS broker_name,
#                 COALESCE(sp_sum.receipted_amount, 0) AS receipted_amount,
#                 ROUND((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40, 2) AS levies,
#                 ROUND(
#                     COALESCE(sp_sum.receipted_amount, 0) -
#                     ((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40),
#                 2) AS available_allocation,
#                 CASE
#                     WHEN t.transactionstotalamount >
#                          COALESCE(sp_sum.receipted_amount, 0) + 1
#                         THEN 'Partially Paid'
#                     ELSE 'Fully Paid'
#                 END AS payment_status,
#                 p2.primarybenefitname,
#                 p.customerspolicycode,
#                 p2.primarybenefitcode
#             FROM pushnote p
#             LEFT JOIN transactions t
#                 ON p.pushnotecode = t.transactionsnumber
#             JOIN intermediary i
#                 ON p.pushnoteagentcode = i.intermediarycode
#             JOIN customerspolicy c
#                 ON p.customerscode = c.customerscode
#             JOIN customers cus
#                 ON p.customerscode = cus.customerscode    

#             LEFT JOIN (
#                 SELECT
#                     sap_payment_drcrno,
#                     SUM(sap_payment_allocateamount) AS receipted_amount
#                 FROM sap_payment
#                 GROUP BY sap_payment_drcrno
#             ) sp_sum
#                 ON p.pushnotedrcrnotenumber = sp_sum.sap_payment_drcrno
#             JOIN primarybenefit p2
#                 ON p.customerspolicycode = p2.primarybenefitcode
#         ) sub
# class CommissionFinancialViewPayable(APIView):
#     """Returns commission financial breakdown + syncs to DB (atomic bulk upsert)."""

#     valid_filters = {
#         "push_note_code": "sub.push_note_code",
#         "policy_number": "sub.policy_number",
#         "transaction_number": "sub.transaction_number",
#         "intermediary_name": "sub.intermediary_name",
#         "broker_name": "sub.broker_name",
#         "payment_status": "sub.payment_status",
#         "customer_name": "sub.customer_name",
#         "debit_code": "sub.debit_code",
#     }

#     def get(self, request):

#         where_clauses = [
#             "sub.intermediary_name <> 'DIRECT'",
#             "sub.receipted_amount > 5"
#         ]
#         params = []

#         for param, col in self.valid_filters.items():
#             val = request.query_params.get(param)
#             if val:
#                 where_clauses.append(f"{col}::text ILIKE %s")
#                 params.append(f"%{val}%")

#         where_sql = "WHERE " + " AND ".join(where_clauses)

#         query = f"""
#         SELECT
#             sub.push_note_code,
#             sub.push_note_request_date,
#             sub.policy_number,
#             sub.transaction_number,
#             sub.agent_code,
#             sub.customer_code,
#             sub.intermediary_name,
#             sub.broker_name,
#             sub.receipted_amount,
#             sub.levies,
#             sub.available_allocation,
#             ROUND(sub.available_allocation * 0.10, 2) AS broker_commission,
#             ROUND(sub.available_allocation * 0.10 * 0.10, 2) AS withholding_tax,
#             ROUND(
#                 (sub.available_allocation * 0.10) -
#                 (sub.available_allocation * 0.10 * 0.10),
#             2) AS commission_payable,
#             sub.transaction_total_amount,
#             sub.payment_status,
#             sub.primarybenefitname,
#             sub.customerspolicycode,
#             sub.primarybenefitcode,
#             sub.customer_name,
#             sub.debit_code
#         FROM (
#             SELECT
#                 p.pushnotecode AS push_note_code,
#                 p.pushnotereqdatetime AS push_note_request_date,
#                 p.pushnotepolicynumber AS policy_number,
#                 t.transactionsnumber AS transaction_number,
#                 p.pushnoteagentcode AS agent_code,
#                 p.customerscode AS customer_code,
#                 t.transactionstotalamount AS transaction_total_amount,
#                 i.intermediaryname AS intermediary_name,
#                 cus.customernamebytype AS customer_name,
#                 p.pushnotedrcrnotenumber AS debit_code,

#                 c.customerspolicyagentbrokername AS broker_name,
#                 COALESCE(sp_sum.receipted_amount, 0) AS receipted_amount,
#                 ROUND((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40, 2) AS levies,
#                 ROUND(
#                     COALESCE(sp_sum.receipted_amount, 0) -
#                     ((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40),
#                 2) AS available_allocation,
#                 CASE
#                     WHEN t.transactionstotalamount >
#                          COALESCE(sp_sum.receipted_amount, 0) + 1
#                         THEN 'Partially Paid'
#                     ELSE 'Fully Paid'
#                 END AS payment_status,
#                 p2.primarybenefitname,
#                 p.customerspolicycode,
#                 p2.primarybenefitcode
#             FROM pushnote p
#             LEFT JOIN transactions t
#                 ON p.pushnotecode = t.transactionsnumber
#             JOIN intermediary i
#                 ON p.pushnoteagentcode = i.intermediarycode
#             JOIN customerspolicy c
#                 ON p.customerscode = c.customerscode
#             JOIN customers cus
#                 ON p.customerscode = cus.customerscode    

#             LEFT JOIN (
#                 SELECT
#                     sap_payment_drcrno,
#                     SUM(sap_payment_allocateamount) AS receipted_amount
#                 FROM sap_payment
#                 GROUP BY sap_payment_drcrno
#             ) sp_sum
#                 ON p.pushnotedrcrnotenumber = sp_sum.sap_payment_drcrno
#             JOIN primarybenefit p2
#                 ON p.customerspolicycode = p2.primarybenefitcode
#         ) sub
#         {where_sql}
#         """

#         try:
#             # 🔥 FETCH
#             with connections['default_betterlife'].cursor() as cursor:
#                 cursor.execute(query, params)
#                 columns = [col[0] for col in cursor.description]
#                 results = [dict(zip(columns, row)) for row in cursor.fetchall()]

#             # 🔥 NORMALIZE
#             decimal_fields = [
#                 "receipted_amount", "levies", "available_allocation",
#                 "broker_commission", "withholding_tax",
#                 "commission_payable", "transaction_total_amount"
#             ]

#             text_fields = [
#                 "intermediary_name", "broker_name", "primarybenefitname"
#             ]

#             for row in results:
#                 for f in text_fields:
#                     if row.get(f):
#                         row[f] = row[f].strip()

#                 for f in decimal_fields:
#                     if row.get(f) is not None:
#                         row[f] = Decimal(str(row[f]))

#             # 🔥 ATOMIC UPSERT
#             with transaction.atomic():
#                 push_codes = [r["push_note_code"] for r in results if r.get("push_note_code")]

#                 existing_qs = CommissionRecord.objects.select_for_update().filter(
#                     push_note_code__in=push_codes
#                 )
#                 existing_map = {obj.push_note_code: obj for obj in existing_qs}

#                 to_create = []
#                 to_update = []

#                 update_fields = [
#                     "push_note_request_date",
#                     "policy_number",
#                     "transaction_number",
#                     "agent_code",
#                     "customer_code",
#                     "intermediary_name",
#                     "broker_name",
#                     "receipted_amount",
#                     "levies",
#                     "available_allocation",
#                     "broker_commission",
#                     "withholding_tax",
#                     "commission_payable",
#                     "transaction_total_amount",
#                     "payment_status",
#                     "primarybenefitname",
#                     "customerspolicycode",
#                     "primarybenefitcode",
#                     "customer_name",
#                     "debit_code"
#                 ]

#                 for row in results:
#                     code = row.get("push_note_code")
#                     existing = existing_map.get(code)

#                     if not existing:
#                         to_create.append(CommissionRecord(**row))
#                         continue

#                     changed = False
#                     for field in update_fields:
#                         if getattr(existing, field) != row.get(field):
#                             setattr(existing, field, row.get(field))
#                             changed = True

#                     if changed:
#                         to_update.append(existing)

#                 if to_create:
#                     CommissionRecord.objects.bulk_create(to_create, batch_size=500)

#                 if to_update:
#                     CommissionRecord.objects.bulk_update(to_update, update_fields, batch_size=500)

#             # summary = {
#             #     "created": len(to_create),
#             #     "updated": len(to_update),
#             #     "skipped": len(results) - len(to_create) - len(to_update),
#             #     "total": len(results),
#             # }

#             # # 🔥 PAGINATION
#             # if request.query_params.get('paginate', '').lower() == 'false':
#             #     return Response({"summary": summary, "data": results})

#             # paginator = PageNumberPagination()
#             # paginated = paginator.paginate_queryset(results, request, view=self)

#             # return paginator.get_paginated_response({
#             #     "summary": summary,
#             #     "results": paginated
#             # })
#             summary = {
#             "created": len(to_create),
#             "updated": len(to_update),
#             "skipped": len(results) - len(to_create) - len(to_update),
#             "total": len(results),
#         }

#         # 🔥 NON-PAGINATED RESPONSE
#             if request.query_params.get('paginate', '').lower() == 'false':
#                 return Response({
#                     "success": True,
#                     "summary": summary,
#                     "data": results
#                 })

#             # 🔥 PAGINATED RESPONSE (UNIFIED FORMAT)
#             paginator = PageNumberPagination()
#             paginated = paginator.paginate_queryset(results, request, view=self)

#             return Response({
#                 "success": True,
#                 "summary": summary,
#                 "pagination": {
#                     "count": paginator.page.paginator.count,
#                     "next": paginator.get_next_link(),
#                     "previous": paginator.get_previous_link(),
#                 },
#                 "results": paginated
#             })
#         except Exception as e:
#             return Response(
#                 {"success": False, "error": str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )
            

    

# class CommissionFinancialViewPayable(APIView):
#     """Returns commission financial breakdown (allocation, broker commission, withholding tax)."""

#     valid_filters = {
#         "push_note_code": "sub.push_note_code",
#         "policy_number": "sub.policy_number",
#         "transaction_number": "sub.transaction_number",
#         "intermediary_name": "sub.intermediary_name",
#         "broker_name": "sub.broker_name",
#         "payment_status": "sub.payment_status",
#     }

#     def get(self, request):

#         # Base filters
#         where_clauses = [
#             "sub.intermediary_name <> 'DIRECT'",
#             "sub.receipted_amount > 5"
#         ]
#         params = []

#         # Dynamic filters
#         for param, col in self.valid_filters.items():
#             val = request.query_params.get(param)
#             if val:
#                 where_clauses.append(f"{col}::text ILIKE %s")
#                 params.append(f"%{val}%")

#         where_sql = "WHERE " + " AND ".join(where_clauses)

#         query = f"""
#         SELECT
#             sub.push_note_code,
#             sub.push_note_request_date,
#             sub.policy_number,
#             sub.transaction_number,
#             sub.agent_code,
#             sub.customer_code,
#             sub.intermediary_name,
#             sub.broker_name,

#             sub.receipted_amount,
#             sub.levies,
#             sub.available_allocation,

#             ROUND(sub.available_allocation * 0.10, 2) AS broker_commission,
#             ROUND(sub.available_allocation * 0.10 * 0.10, 2) AS withholding_tax,
#             ROUND(
#                 (sub.available_allocation * 0.10) -
#                 (sub.available_allocation * 0.10 * 0.10),
#             2) AS commission_payable,

#             sub.transaction_total_amount,
#             sub.payment_status,

#             sub.primarybenefitname,
#             sub.customerspolicycode,
#             sub.primarybenefitcode

#         FROM (
#             SELECT
#                 p.pushnotecode AS push_note_code,
#                 p.pushnotereqdatetime AS push_note_request_date,
#                 p.pushnotepolicynumber AS policy_number,
#                 t.transactionsnumber AS transaction_number,
#                 p.pushnoteagentcode AS agent_code,
#                 p.customerscode AS customer_code,
#                 t.transactionstotalamount AS transaction_total_amount,
#                 i.intermediaryname AS intermediary_name,
#                 c.customerspolicyagentbrokername AS broker_name,

#                 COALESCE(sp_sum.receipted_amount, 0) AS receipted_amount,

#                 ROUND((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40, 2) AS levies,

#                 ROUND(
#                     COALESCE(sp_sum.receipted_amount, 0) -
#                     ((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40),
#                 2) AS available_allocation,

#                 CASE
#                     WHEN t.transactionstotalamount >
#                          COALESCE(sp_sum.receipted_amount, 0) + 1
#                         THEN 'Partially Paid'
#                     ELSE 'Fully Paid'
#                 END AS payment_status,

#                 p2.primarybenefitname,
#                 p.customerspolicycode,
#                 p2.primarybenefitcode

#             FROM pushnote p

#             LEFT JOIN transactions t
#                 ON p.pushnotecode = t.transactionsnumber

#             JOIN intermediary i
#                 ON p.pushnoteagentcode = i.intermediarycode

#             JOIN customerspolicy c
#                 ON p.customerscode = c.customerscode

#             LEFT JOIN (
#                 SELECT
#                     sap_payment_drcrno,
#                     SUM(sap_payment_allocateamount) AS receipted_amount
#                 FROM sap_payment
#                 GROUP BY sap_payment_drcrno
#             ) sp_sum
#                 ON p.pushnotedrcrnotenumber = sp_sum.sap_payment_drcrno

#             JOIN primarybenefit p2
#                 ON p.customerspolicycode = p2.primarybenefitcode

#             WHERE i.intermediaryname <> 'DIRECT'
#               AND COALESCE(sp_sum.receipted_amount, 0) > 5
#               AND t.transactionstotalamount <= COALESCE(sp_sum.receipted_amount, 0) + 1
#         ) sub

#         {where_sql}
#         """

#         try:
#             with connections['default_betterlife'].cursor() as cursor:
#                 cursor.execute(query, params)
#                 columns = [col[0] for col in cursor.description]
#                 results = [dict(zip(columns, row)) for row in cursor.fetchall()]

#             if request.query_params.get('paginate', '').lower() == 'false':
#                 return Response(results)

#             paginator = PageNumberPagination()
#             paginated = paginator.paginate_queryset(results, request, view=self)

#             return paginator.get_paginated_response(paginated)

#         except Exception as e:
#             return Response(
#                 {"success": False, "error": str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )
            
#             # sap_payment_clientname
            
class AgentBrokersView(APIView):
    """ Returns agents and brokers combined with intermediary details """
    
    valid_filters = {
        'agentbrokercode': 'ab.agentbrokercode',
        'agentbrokername': 'ab.agentbrokername',
        'intermediarycode': 'ab.intermediarycode',
        'agentbrokerenabled': 'ab.agentbrokerenabled',
        'branchcode': 'ab.branchcode',
        'agentbrokeraccountname': 'ab.agentbrokeraccountname',
        'agentbrokeraccount': 'ab.agentbrokeraccount',
        'agentbrokeremailaddress': 'ab.agentbrokeremailaddress',
        'agentbrokeraccountnumber': 'ab.agentbrokeraccountnumber',
        'bankcode': 'ab.bankcode',
        'bankbranchcode': 'ab.bankbranchcode',
        'agentbrokerphonenumber': 'ab.agentbrokerphonenumber',
        'intermediaryname': 'i.intermediaryname',
        'intermediarycommisionrate': 'i.intermediarycommisionrate',
        'intermediarywithholdingtax': 'i.intermediarywithholdingtax',
        'intermediaryenabled': 'i.intermediaryenabled',
        'intermediarynameindex': 'i.intermediarynameindex',
        'intermediaryclass': 'i.intermediaryclass'
    }

    def get(self, request):
        where_clauses = []
        params = []

        # 1. Exact Match Filters
        for param, col in self.valid_filters.items():
            val = request.query_params.get(param)
            if val:
                where_clauses.append(f"{col}::text = %s")
                params.append(val)

        # 2. Global Search Filter
        search = request.query_params.get('search')
        if search:
            search_cols = list(self.valid_filters.values())
            search_clause = " OR ".join([f"{col}::text ILIKE %s" for col in search_cols])
            where_clauses.append(f"({search_clause})")
            params.extend([f"%{search}%"] * len(search_cols))

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # 3. Base Query
        query = f"""
            SELECT 
                ab.agentbrokercode,
                ab.agentbrokername,
                ab.intermediarycode,
                ab.agentbrokerenabled,
                ab.branchcode,
                ab.agentbrokeraccountname,
                ab.agentbrokeraccount,
                ab.agentbrokeremailaddress,
                ab.agentbrokeraccountnumber,
                ab.bankcode,
                ab.bankbranchcode,
                ab.agentbrokerphonenumber,
                i.intermediaryname,
                i.intermediarycommisionrate,
                i.intermediarywithholdingtax,
                i.intermediaryenabled,
                i.intermediarynameindex,
                i.intermediaryclass
            FROM public.agentbroker ab
            JOIN public.intermediary i 
                ON ab.intermediarycode = i.intermediarycode
            {where_sql}
        """

        # 4. Ordering
        outer_order = ""
        req_order = request.query_params.get('ordering')
        if req_order:
            desc = req_order.startswith('-')
            field = req_order.lstrip('-')
            if field in self.valid_filters:
                outer_order = f"ORDER BY {field} {'DESC' if desc else 'ASC'}"

        final_query = f"{query} {outer_order}"

        try:
            with connections['default_betterlife'].cursor() as cursor:
                cursor.execute(final_query, params)
                columns = [col[0] for col in cursor.description]
                results = [
                    dict(zip(columns, row))
                    for row in cursor.fetchall()
                ]

            # Return all records at once without pagination
            serializer = AgentBrokerSerializer(results, many=True)
            return Response(serializer.data)


        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
             
             
             
from django.utils import timezone
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from django.utils import timezone
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import CommissionRecord

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction, connections
from django.utils import timezone

from .models import CommissionRecord


class CommissionPayUpdateView(APIView):

    def post(self, request):
        try:
            data = request.data.get("data")

            # =========================
            # ✅ VALIDATION
            # =========================
            if not isinstance(data, list) or len(data) == 0:
                return Response(
                    {"success": False, "message": "Data must be a non-empty list"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            debit_codes = list({
                item.get("debit_code")
                for item in data
                if item.get("debit_code")
            })

            if not debit_codes:
                return Response(
                    {"success": False, "message": "Missing valid debit_code(s)"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            user = (
                request.user.username
                if request.user and request.user.is_authenticated
                else "system"
            )

            now = timezone.now()

            # =========================
            # 🔐 LOCAL DB UPDATE
            # =========================
            with transaction.atomic():
                qs = CommissionRecord.objects.select_for_update().filter(
                    debit_code__in=debit_codes
                )

                if not qs.exists():
                    return Response(
                        {"success": False, "message": "No matching records found"},
                        status=status.HTTP_404_NOT_FOUND
                    )

                local_updated = qs.update(
                    is_paid=True,
                    payment_status="Fully Paid",
                    paid_by=user,
                    paid_at=now
                )

            # =========================
            # 🔗 BETTERLIFE DB UPDATE
            # =========================
            external_updated = 0

            with connections["default_betterlife"].cursor() as cursor:
                cursor.execute("""
                    UPDATE pushnote
                    SET commission_paid = 1,
                        paid_by = %s,
                        paid_at = %s
                    WHERE debit = ANY(%s)
                """, [user, now, debit_codes])

                external_updated = cursor.rowcount

            # =========================
            # ✅ RESPONSE
            # =========================
            return Response({
                "success": True,
                "message": "Payments updated successfully",
                "local_updated": local_updated,
                "external_updated": external_updated,
                "debit_codes": debit_codes
            })

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
# class CommissionPayUpdateView(APIView):
#     """
#     Marks commissions as Fully Paid using debit_code
#     """

#     def post(self, request):
#         try:
#             data = request.data.get("data")

#             # ✅ STRICT VALIDATION
#             if not isinstance(data, list) or len(data) == 0:
#                 return Response(
#                     {"success": False, "message": "Data must be a non-empty list"},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )

#             debit_codes = list({
#                 item.get("debit_code")
#                 for item in data
#                 if item.get("debit_code")
#             })

#             if not debit_codes:
#                 return Response(
#                     {"success": False, "message": "Missing valid debit_code(s)"},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )

#             user = (
#                 request.user.username
#                 if request.user and request.user.is_authenticated
#                 else "system"
#             )

#             with transaction.atomic():
#                 qs = CommissionRecord.objects.select_for_update().filter(
#                     debit_code__in=debit_codes
#                 )

#                 if not qs.exists():
#                     return Response(
#                         {"success": False, "message": "No matching records found"},
#                         status=status.HTTP_404_NOT_FOUND
#                     )

#                 updated_count = qs.update(
#                     is_paid=True,
#                     payment_status="Fully Paid",
#                     paid_by=user,
#                     paid_at=timezone.now()
#                 )

#             return Response({
#                 "success": True,
#                 "message": "Payments updated successfully",
#                 "updated_records": updated_count,
#                 "debit_codes": debit_codes
#             })

#         except Exception as e:
#             return Response(
#                 {"success": False, "error": str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )

# from .models import CommissionRecord


# class CommissionPayUpdateView(APIView):
#     """
#     Marks commissions as paid using debit_code
#     """

#     def post(self, request):
#         try:
#             data = request.data.get("data", [])

#             if not data:
#                 return Response(
#                     {"success": False, "message": "No data provided"},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )

#             debit_codes = [item.get("debit_code") for item in data if item.get("debit_code")]

#             if not debit_codes:
#                 return Response(
#                     {"success": False, "message": "Missing debit_code"},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )

#             user = request.user.username if request.user.is_authenticated else "system"

#             with transaction.atomic():
#                 records = CommissionRecord.objects.filter(
#                     debit_code__in=debit_codes
#                 )

#                 updated_count = records.update(
#                     is_paid=True,
#                     payment_status="Fully Paid",
#                     paid_by=user,
#                     paid_at=timezone.now()
#                 )

#             return Response({
#                 "success": True,
#                 "message": "Payments updated successfully",
#                 "updated_records": updated_count
#             })

#         except Exception as e:
#             return Response(
#                 {"success": False, "error": str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )