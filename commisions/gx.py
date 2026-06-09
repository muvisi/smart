
from commisions.models import CommissionRecord
from .serializers import CommissionRecordSerializer, DetailedCommissionRecordSerializer, AgentBrokerSerializer
from django.db import transaction, connections
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination


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

        where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""

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
                {where_sql}
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

            for row in results:
                if row.get("paid_at"):
                    if hasattr(row["paid_at"], "strftime"):
                        row["paid_at"] = row["paid_at"].strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(row["paid_at"], str):
                        try:
                            from datetime import datetime
                            # Handle ISO format string that might be returned by the DB driver
                            dt_obj = datetime.fromisoformat(row["paid_at"].replace('Z', ''))
                            row["paid_at"] = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass # Fallback to original string if format is unknown

            if request.query_params.get('paginate', '').lower() == 'false' or request.query_params.get('export', '').lower() == 'true':
                serializer = DetailedCommissionRecordSerializer(results, many=True)
                return Response(serializer.data)

            paginator = PageNumberPagination()
            paginated_results = paginator.paginate_queryset(results, request, view=self)

            serializer = DetailedCommissionRecordSerializer(paginated_results, many=True)
            return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from django.db import connections
# from rest_framework.pagination import PageNumberPagination
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from django.db import connections
# from rest_framework.pagination import PageNumberPagination


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
            
            
            
# from rest_framework.response import Response
# from rest_framework import status
# from django.db import connections
# from rest_framework.pagination import PageNumberPagination


# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from django.db import connections
# from rest_framework.pagination import PageNumberPagination
# from decimal import Decimal
# from django.db import connections, transaction
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from rest_framework.pagination import PageNumberPagination

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
            "sub.receipted_amount > 5"
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
#             "sub.receipted_amount > 5",
#             "sub.payment_status = 'Fully Paid'"  # ✅ ADDED FILTER
#         ]
#         params = []

#         for param, col in self.valid_filters.items():
#             val = request.query_params.get(param)
#             if val:
#                 where_clauses.append(f"{col}::text ILIKE %s")
#                 params.append(f"%{val}%")

#         # Filters by the dates
#         receipt_date = request.query_params.get("receipt_date")
#         receipt_date_from = request.query_params.get("start_date")
#         receipt_date_to = request.query_params.get("end_date")

#         # Exact date
#         if receipt_date:
#             where_clauses.append("DATE(sub.receipt_date) = %s")
#             params.append(receipt_date)

#         # Date range
#         if receipt_date_from and receipt_date_to:
#             where_clauses.append(
#                 "DATE(sub.receipt_date) BETWEEN %s AND %s"
#             )
#             params.extend([receipt_date_from, receipt_date_to])

#         # From date only
#         elif receipt_date_from:
#             where_clauses.append("DATE(sub.receipt_date) >= %s")
#             params.append(receipt_date_from)

#         # To date only
#         elif receipt_date_to:
#             where_clauses.append("DATE(sub.receipt_date) <= %s")
#             params.append(receipt_date_to)

#         where_sql = "WHERE " + " AND ".join(where_clauses)

#         query = f"""
#         SELECT
#     sub.push_note_code,
#     sub.push_note_request_date,
#     sub.policy_number,
#     sub.transaction_number,
#     sub.agent_code,
#     sub.customer_code,
#     sub.intermediary_name,
#     sub.broker_name,
#     sub.receipted_amount,
#     sub.levies,
#     sub.available_allocation,

#     -- ✅ UPDATED: dynamic commission
#     ROUND(
#         sub.available_allocation * (sub.intermediarycommisionrate / 100),
#     2) AS broker_commission,

#     -- ✅ UPDATED: dynamic withholding tax
#     ROUND(
#         sub.available_allocation * (sub.intermediarycommisionrate / 100) *
#         (sub.intermediarywithholdingtax / 100),
#     2) AS withholding_tax,

#     -- ✅ UPDATED: dynamic commission payable
#     ROUND(
#         (sub.available_allocation * (sub.intermediarycommisionrate / 100)) -
#         (
#             sub.available_allocation * (sub.intermediarycommisionrate / 100) *
#             (sub.intermediarywithholdingtax / 100)
#         ),
#     2) AS commission_payable,

#     sub.transaction_total_amount,
#     sub.payment_status,
#     sub.primarybenefitname,
#     sub.customerspolicycode,
#     sub.primarybenefitcode,
#     sub.customer_name,
#     sub.debit_code,
#     sub.receipt_date 
    

# FROM (
#     SELECT
#         p.pushnotecode AS push_note_code,
#         p.pushnotereqdatetime AS push_note_request_date,
#         p.pushnotepolicynumber AS policy_number,
#         t.transactionsnumber AS transaction_number,
#         p.pushnoteagentcode AS agent_code,
#         p.customerscode AS customer_code,
#         t.transactionstotalamount AS transaction_total_amount,

#         i.intermediaryname AS intermediary_name,

#         -- ✅ ADDED: bring rates into subquery
#         i.intermediarycommisionrate,
#         i.intermediarywithholdingtax,

#         cus.customernamebytype AS customer_name,
#         p.pushnotedrcrnotenumber AS debit_code,

#         c.customerspolicyagentbrokername AS broker_name,

#         COALESCE(sp_sum.receipted_amount, 0) AS receipted_amount,
#         sp_sum.receipt_date,
        

#         ROUND(
#             (COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40,
#         2) AS levies,

#         ROUND(
#             COALESCE(sp_sum.receipted_amount, 0) -
#             ((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40),
#         2) AS available_allocation,

#         CASE
#             WHEN t.transactionstotalamount >
#                  COALESCE(sp_sum.receipted_amount, 0) + 1
#                 THEN 'Partially Paid'
#             ELSE 'Fully Paid'
#         END AS payment_status,

#         p2.primarybenefitname,
#         p.customerspolicycode,
#         p2.primarybenefitcode

#     FROM pushnote p

#     LEFT JOIN transactions t
#         ON p.pushnotecode = t.transactionsnumber

#     JOIN intermediary i
#         ON p.pushnoteagentcode = i.intermediarycode

#     JOIN customerspolicy c
#         ON p.customerscode = c.customerscode

#     JOIN customers cus
#         ON p.customerscode = cus.customerscode    

#     LEFT JOIN (
#         SELECT
#             sap_payment_drcrno,
#             SUM(sap_payment_allocateamount) AS receipted_amount,
#             MAX(sap_payment_receiptdate) AS receipt_date
#         FROM sap_payment
#         GROUP BY sap_payment_drcrno
#     ) sp_sum
#         ON p.pushnotedrcrnotenumber = sp_sum.sap_payment_drcrno

#     JOIN primarybenefit p2
#         ON p.customerspolicycode = p2.primarybenefitcode
        
#     WHERE p.commission_paid IS NULL OR p.commission_paid = 0    

# ) sub
        
#         {where_sql}
#         """

#         try:
#             with connections['default_betterlife'].cursor() as cursor:
#                 cursor.execute(query, params)
#                 columns = [col[0] for col in cursor.description]
#                 results = [dict(zip(columns, row)) for row in cursor.fetchall()]

#             if (request.query_params.get('paginate', '').lower() == 'false'
#                     or request.query_params.get('export', '').lower() == 'true'):
#                 return Response(results)

#             paginator = PageNumberPagination()
#             paginated = paginator.paginate_queryset(results, request, view=self)

#             return paginator.get_paginated_response(paginated)

#         except Exception as e:
#             return Response(
#                 {"success": False, "error": str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )

class CommissionFinancialViewPaid(APIView):
    """Returns paid commission financial breakdown."""

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

        where_clauses = []
        params = []

        for param, col in self.valid_filters.items():
            val = request.query_params.get(param)
            if val:
                where_clauses.append(f"{col}::text ILIKE %s")
                params.append(f"%{val}%")

        where_sql = ""
        if where_clauses:
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

    -- dynamic commission  
    ROUND(  
        sub.available_allocation * (sub.intermediarycommisionrate / 100),  
    2) AS broker_commission,  

    -- dynamic withholding tax  
    ROUND(  
        sub.available_allocation * (sub.intermediarycommisionrate / 100) *  
        (sub.intermediarywithholdingtax / 100),  
    2) AS withholding_tax,  

    -- dynamic commission payable  
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
    sub.debit_code,  
    sub.paid_by,  
    sub.commission_paid,  
    sub.paid_at,  
    -- Commission status text  
    CASE WHEN sub.commission_paid = 1 THEN 'PAID' ELSE 'UNPAID' END AS commission_status  

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
        p2.primarybenefitcode,  
        p.paid_by,  
        p.commission_paid,  
        TO_CHAR(p.paid_at, 'YYYY-MM-DD HH24:MI:SS') AS paid_at  

    FROM pushnote p  

    LEFT JOIN transactions t  
        ON p.pushnotecode = t.transactionsnumber  

    JOIN intermediary i  
        ON p.pushnoteagentcode = i.intermediarycode  

    JOIN customerspolicy c  
        -- ON p.customerscode = c.customerscode  
        -- UPDATING QUERY TO SELECT BY POLICY NUMBER INSTEAD OF CUSTOMER CODE
        ON p.pushnotepolicynumber = c.customerspolicynumber

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

    WHERE p.commission_paid = 1
) sub
        
        {where_sql}
        """

        try:
            with connections['default_betterlife'].cursor() as cursor:
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]

            if request.query_params.get('paginate', '').lower() == 'false':
                return Response({
                    "success": True,
                    "data": results
                })

            paginator = PageNumberPagination()
            paginated = paginator.paginate_queryset(results, request, view=self)

            return Response({
                "success": True,
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


from .models import CommissionRecord


# class CommissionFinancialViewPayable(APIView):
#     """
#     Returns commission financial breakdown
#     + atomically syncs records into CommissionRecord table.
#     """

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

#             ROUND(
#                 sub.available_allocation *
#                 (sub.intermediarycommisionrate / 100),
#                 2
#             ) AS broker_commission,

#             ROUND(
#                 sub.available_allocation *
#                 (sub.intermediarycommisionrate / 100) *
#                 (sub.intermediarywithholdingtax / 100),
#                 2
#             ) AS withholding_tax,

#             ROUND(
#                 (
#                     sub.available_allocation *
#                     (sub.intermediarycommisionrate / 100)
#                 ) -
#                 (
#                     sub.available_allocation *
#                     (sub.intermediarycommisionrate / 100) *
#                     (sub.intermediarywithholdingtax / 100)
#                 ),
#                 2
#             ) AS commission_payable,

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

#                 COALESCE(i.intermediarycommisionrate, 0)
#                     AS intermediarycommisionrate,

#                 COALESCE(i.intermediarywithholdingtax, 0)
#                     AS intermediarywithholdingtax,

#                 cus.customernamebytype AS customer_name,

#                 p.pushnotedrcrnotenumber AS debit_code,

#                 c.customerspolicyagentbrokername AS broker_name,

#                 COALESCE(sp_sum.receipted_amount, 0)
#                     AS receipted_amount,

#                 ROUND(
#                     (
#                         COALESCE(sp_sum.receipted_amount, 0) *
#                         0.45 / 100
#                     ) + 40,
#                     2
#                 ) AS levies,

#                 ROUND(
#                     COALESCE(sp_sum.receipted_amount, 0) -
#                     (
#                         (
#                             COALESCE(sp_sum.receipted_amount, 0) *
#                             0.45 / 100
#                         ) + 40
#                     ),
#                     2
#                 ) AS available_allocation,

#                 CASE
#                     WHEN t.transactionstotalamount >
#                          COALESCE(sp_sum.receipted_amount, 0) + 1
#                     THEN 'Partially Paid'
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
#                     SUM(sap_payment_allocateamount)
#                         AS receipted_amount
#                 FROM sap_payment
#                 GROUP BY sap_payment_drcrno
#             ) sp_sum
#                 ON p.pushnotedrcrnotenumber =
#                    sp_sum.sap_payment_drcrno

#             JOIN primarybenefit p2
#                 ON p.customerspolicycode =
#                    p2.primarybenefitcode

#             WHERE
#                 p.commission_paid IS NULL
#                 OR p.commission_paid = 0

#         ) sub

#         {where_sql}
#         """

#         try:

#             with transaction.atomic():

#                 with connections['default_betterlife'].cursor() as cursor:

#                     cursor.execute(query, params)

#                     columns = [col[0] for col in cursor.description]

#                     results = [
#                         dict(zip(columns, row))
#                         for row in cursor.fetchall()
#                     ]

#                 # =========================
#                 # BULK UPSERT
#                 # =========================

#                 commission_objects = []

#                 for row in results:

#                     commission_objects.append(
#                         CommissionRecord(
#                             push_note_code=row.get("push_note_code"),
#                             transaction_number=row.get("transaction_number"),
#                             debit_code=row.get("debit_code"),
#                             policy_number=row.get("policy_number"),
#                             customer_name=row.get("customer_name"),

#                             agent_code=row.get("agent_code"),
#                             customer_code=row.get("customer_code"),

#                             intermediary_name=row.get("intermediary_name"),
#                             broker_name=row.get("broker_name"),

#                             push_note_request_date=row.get(
#                                 "push_note_request_date"
#                             ),

#                             receipted_amount=row.get(
#                                 "receipted_amount"
#                             ),

#                             levies=row.get("levies"),

#                             available_allocation=row.get(
#                                 "available_allocation"
#                             ),

#                             broker_commission=row.get(
#                                 "broker_commission"
#                             ),

#                             withholding_tax=row.get(
#                                 "withholding_tax"
#                             ),

#                             commission_payable=row.get(
#                                 "commission_payable"
#                             ),

#                             transaction_total_amount=row.get(
#                                 "transaction_total_amount"
#                             ),

#                             payment_status=row.get(
#                                 "payment_status"
#                             ),

#                             primarybenefitname=row.get(
#                                 "primarybenefitname"
#                             ),

#                             customerspolicycode=row.get(
#                                 "customerspolicycode"
#                             ),

#                             primarybenefitcode=row.get(
#                                 "primarybenefitcode"
#                             ),
#                         )
#                     )

#                 CommissionRecord.objects.bulk_create(
#                     commission_objects,
#                     update_conflicts=True,
#                     unique_fields=["debit_code"],
#                     update_fields=[
#                         "push_note_code",
#                         "transaction_number",
#                         "policy_number",
#                         "customer_name",

#                         "agent_code",
#                         "customer_code",

#                         "intermediary_name",
#                         "broker_name",

#                         "push_note_request_date",

#                         "receipted_amount",
#                         "levies",
#                         "available_allocation",

#                         "broker_commission",
#                         "withholding_tax",
#                         "commission_payable",

#                         "transaction_total_amount",

#                         "payment_status",

#                         "primarybenefitname",
#                         "customerspolicycode",
#                         "primarybenefitcode",

#                         "updated_at",
#                     ]
#                 )

#                 # =========================
#                 # RESPONSE
#                 # =========================

#                 if (
#                     request.query_params.get(
#                         'paginate', ''
#                     ).lower() == 'false'
#                 ):
#                     return Response(results)

#                 paginator = PageNumberPagination()

#                 paginated = paginator.paginate_queryset(
#                     results,
#                     request,
#                     view=self
#                 )

#                 return paginator.get_paginated_response(
#                     paginated
#                 )

#         except Exception as e:

#             return Response(
#                 {
#                     "success": False,
#                     "error": str(e)
#                 },
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )

from django.db import transaction, connections
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination

from commisions.models import CommissionRecord

from django.db import transaction, connections
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from commisions.models import CommissionRecord


class CommissionFinancialViewPayable(APIView):
    """Returns ONLY valid fully paid commissions and syncs them atomically."""

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

        try:

            where_clauses = [
                "sub.payment_status = 'Fully Paid'",
                "sub.available_allocation > 1"
            ]
            params = []

            for param, col in self.valid_filters.items():
                val = request.query_params.get(param)
                if val:
                    where_clauses.append(f"{col}::text ILIKE %s")
                    params.append(f"%{val}%")

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

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

                    COALESCE(i.intermediarycommisionrate, 0)
                        AS intermediarycommisionrate,

                    COALESCE(i.intermediarywithholdingtax, 0)
                        AS intermediarywithholdingtax,

                    cus.customernamebytype AS customer_name,

                    p.pushnotedrcrnotenumber AS debit_code,

                    c.customerspolicyagentbrokername AS broker_name,

                    COALESCE(sp_sum.receipted_amount, 0)
                        AS receipted_amount,

                    ROUND(
                        (COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40,
                        2
                    ) AS levies,

                    ROUND(
                        COALESCE(sp_sum.receipted_amount, 0) -
                        ((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40),
                        2
                    ) AS available_allocation,

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
                    -- ON p.customerscode = c.customerscode
                    -- UPDATING QUERY TO SELECT BY POLICY NUMBER INSTEAD OF CUSTOMER CODE
                    on p.pushnotepolicynumber = c.customerspolicynumber

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

                WHERE
                    (p.commission_paid IS NULL OR p.commission_paid = 0)

             ) sub

             {where_sql}
             """

            with connections['default_betterlife'].cursor() as cursor:
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]

            # ==============================
            # ATOMIC SYNC
            # ==============================

            with transaction.atomic():

                debit_codes = list({
                    r.get("debit_code")
                    for r in results
                    if r.get("debit_code")
                })

                existing_map = {
                    obj.debit_code: obj
                    for obj in CommissionRecord.objects.filter(
                        debit_code__in=debit_codes
                    )
                }

                to_create = []
                to_update = []

                for row in results:

                    debit_code = row.get("debit_code")
                    obj = existing_map.get(debit_code)

                    if obj:

                        obj.push_note_code = row.get("push_note_code")
                        obj.transaction_number = row.get("transaction_number")
                        obj.policy_number = row.get("policy_number")
                        obj.customer_name = row.get("customer_name")

                        obj.agent_code = row.get("agent_code")
                        obj.customer_code = row.get("customer_code")

                        obj.intermediary_name = row.get("intermediary_name")
                        obj.broker_name = row.get("broker_name")

                        obj.push_note_request_date = row.get("push_note_request_date")

                        obj.receipted_amount = row.get("receipted_amount")
                        obj.levies = row.get("levies")
                        obj.available_allocation = row.get("available_allocation")

                        obj.broker_commission = row.get("broker_commission")
                        obj.withholding_tax = row.get("withholding_tax")
                        obj.commission_payable = row.get("commission_payable")

                        obj.transaction_total_amount = row.get("transaction_total_amount")
                        obj.payment_status = row.get("payment_status")

                        obj.primarybenefitname = row.get("primarybenefitname")
                        obj.customerspolicycode = row.get("customerspolicycode")
                        obj.primarybenefitcode = row.get("primarybenefitcode")

                        obj.updated_at = timezone.now()

                        to_update.append(obj)

                    else:

                        to_create.append(
                            CommissionRecord(
                                push_note_code=row.get("push_note_code"),
                                transaction_number=row.get("transaction_number"),
                                debit_code=debit_code,
                                policy_number=row.get("policy_number"),
                                customer_name=row.get("customer_name"),

                                agent_code=row.get("agent_code"),
                                customer_code=row.get("customer_code"),

                                intermediary_name=row.get("intermediary_name"),
                                broker_name=row.get("broker_name"),

                                push_note_request_date=row.get("push_note_request_date"),

                                receipted_amount=row.get("receipted_amount"),
                                levies=row.get("levies"),
                                available_allocation=row.get("available_allocation"),

                                broker_commission=row.get("broker_commission"),
                                withholding_tax=row.get("withholding_tax"),
                                commission_payable=row.get("commission_payable"),

                                transaction_total_amount=row.get("transaction_total_amount"),
                                payment_status=row.get("payment_status"),

                                primarybenefitname=row.get("primarybenefitname"),
                                customerspolicycode=row.get("customerspolicycode"),
                                primarybenefitcode=row.get("primarybenefitcode"),
                            )
                        )

                if to_create:
                    CommissionRecord.objects.bulk_create(to_create, batch_size=1000)

                if to_update:
                    CommissionRecord.objects.bulk_update(
                        to_update,
                        [
                            "push_note_code",
                            "transaction_number",
                            "policy_number",
                            "customer_name",
                            "agent_code",
                            "customer_code",
                            "intermediary_name",
                            "broker_name",
                            "push_note_request_date",
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
                            "updated_at",
                        ],
                        batch_size=1000
                    )

            # ==============================
            # RESPONSE (PAGINATION)
            # ==============================

            if (
                    request.query_params.get('paginate', '').lower() == 'false'
                    or request.query_params.get('export', '').lower() == 'true'
            ):
                return Response(results)

            paginator = PageNumberPagination()
            paginated = paginator.paginate_queryset(results, request, view=self)

            return paginator.get_paginated_response(paginated)

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=500
            )
# class CommissionFinancialViewPayable(APIView):
#     """Returns commission financial breakdown + atomic sync to CommissionRecord."""

#     def get(self, request):

#         try:
#             where_clauses = [
#                 "sub.intermediary_name <> 'DIRECT'",
#                 "sub.receipted_amount > 5"
#             ]

#             params = []

#             query = """
#             SELECT
#                 sub.push_note_code,
#                 sub.push_note_request_date,
#                 sub.policy_number,
#                 sub.transaction_number,
#                 sub.agent_code,
#                 sub.customer_code,
#                 sub.intermediary_name,
#                 sub.broker_name,
#                 sub.receipted_amount,
#                 sub.levies,
#                 sub.available_allocation,

#                 ROUND(
#                     sub.available_allocation *
#                     (sub.intermediarycommisionrate / 100),
#                     2
#                 ) AS broker_commission,

#                 ROUND(
#                     sub.available_allocation *
#                     (sub.intermediarycommisionrate / 100) *
#                     (sub.intermediarywithholdingtax / 100),
#                     2
#                 ) AS withholding_tax,

#                 ROUND(
#                     (
#                         sub.available_allocation *
#                         (sub.intermediarycommisionrate / 100)
#                     ) -
#                     (
#                         sub.available_allocation *
#                         (sub.intermediarycommisionrate / 100) *
#                         (sub.intermediarywithholdingtax / 100)
#                     ),
#                     2
#                 ) AS commission_payable,

#                 sub.transaction_total_amount,
#                 sub.payment_status,
#                 sub.primarybenefitname,
#                 sub.customerspolicycode,
#                 sub.primarybenefitcode,
#                 sub.customer_name,
#                 sub.debit_code

#             FROM (

#                 SELECT
#                     p.pushnotecode AS push_note_code,
#                     p.pushnotereqdatetime AS push_note_request_date,
#                     p.pushnotepolicynumber AS policy_number,
#                     t.transactionsnumber AS transaction_number,
#                     p.pushnoteagentcode AS agent_code,
#                     p.customerscode AS customer_code,

#                     t.transactionstotalamount AS transaction_total_amount,

#                     i.intermediaryname AS intermediary_name,

#                     COALESCE(i.intermediarycommisionrate, 0)
#                         AS intermediarycommisionrate,

#                     COALESCE(i.intermediarywithholdingtax, 0)
#                         AS intermediarywithholdingtax,

#                     cus.customernamebytype AS customer_name,

#                     p.pushnotedrcrnotenumber AS debit_code,

#                     c.customerspolicyagentbrokername AS broker_name,

#                     COALESCE(sp_sum.receipted_amount, 0)
#                         AS receipted_amount,

#                     ROUND(
#                         (COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40,
#                         2
#                     ) AS levies,

#                     ROUND(
#                         COALESCE(sp_sum.receipted_amount, 0) -
#                         ((COALESCE(sp_sum.receipted_amount, 0) * 0.45 / 100) + 40),
#                         2
#                     ) AS available_allocation,

#                     CASE
#                         WHEN t.transactionstotalamount >
#                              COALESCE(sp_sum.receipted_amount, 0) + 1
#                         THEN 'Partially Paid'
#                         ELSE 'Fully Paid'
#                     END AS payment_status,

#                     p2.primarybenefitname,
#                     p.customerspolicycode,
#                     p2.primarybenefitcode

#                 FROM pushnote p

#                 LEFT JOIN transactions t
#                     ON p.pushnotecode = t.transactionsnumber

#                 JOIN intermediary i
#                     ON p.pushnoteagentcode = i.intermediarycode

#                 JOIN customerspolicy c
#                     ON p.customerscode = c.customerscode

#                 JOIN customers cus
#                     ON p.customerscode = cus.customerscode

#                 LEFT JOIN (
#                     SELECT
#                         sap_payment_drcrno,
#                         SUM(sap_payment_allocateamount) AS receipted_amount
#                     FROM sap_payment
#                     GROUP BY sap_payment_drcrno
#                 ) sp_sum
#                     ON p.pushnotedrcrnotenumber = sp_sum.sap_payment_drcrno

#                 JOIN primarybenefit p2
#                     ON p.customerspolicycode = p2.primarybenefitcode

#                 WHERE p.commission_paid IS NULL OR p.commission_paid = 0

#             ) sub
#             """

#             with connections['default_betterlife'].cursor() as cursor:
#                 cursor.execute(query, params)
#                 columns = [col[0] for col in cursor.description]
#                 results = [dict(zip(columns, row)) for row in cursor.fetchall()]

#             # =========================================
#             # ATOMIC SYNC (NO UNIQUE CONSTRAINT NEEDED)
#             # =========================================

#             with transaction.atomic():

#                 debit_codes = list({
#                     r.get("debit_code")
#                     for r in results
#                     if r.get("debit_code")
#                 })

#                 existing_map = {
#                     obj.debit_code: obj
#                     for obj in CommissionRecord.objects.filter(
#                         debit_code__in=debit_codes
#                     )
#                 }

#                 to_create = []
#                 to_update = []

#                 for row in results:

#                     debit_code = row.get("debit_code")
#                     obj = existing_map.get(debit_code)

#                     if obj:

#                         obj.push_note_code = row.get("push_note_code")
#                         obj.transaction_number = row.get("transaction_number")
#                         obj.policy_number = row.get("policy_number")
#                         obj.customer_name = row.get("customer_name")

#                         obj.agent_code = row.get("agent_code")
#                         obj.customer_code = row.get("customer_code")

#                         obj.intermediary_name = row.get("intermediary_name")
#                         obj.broker_name = row.get("broker_name")

#                         obj.push_note_request_date = row.get("push_note_request_date")

#                         obj.receipted_amount = row.get("receipted_amount")
#                         obj.levies = row.get("levies")
#                         obj.available_allocation = row.get("available_allocation")

#                         obj.broker_commission = row.get("broker_commission")
#                         obj.withholding_tax = row.get("withholding_tax")
#                         obj.commission_payable = row.get("commission_payable")

#                         obj.transaction_total_amount = row.get("transaction_total_amount")
#                         obj.payment_status = row.get("payment_status")

#                         obj.primarybenefitname = row.get("primarybenefitname")
#                         obj.customerspolicycode = row.get("customerspolicycode")
#                         obj.primarybenefitcode = row.get("primarybenefitcode")

#                         obj.updated_at = timezone.now()

#                         to_update.append(obj)

#                     else:

#                         to_create.append(
#                             CommissionRecord(
#                                 push_note_code=row.get("push_note_code"),
#                                 transaction_number=row.get("transaction_number"),
#                                 debit_code=debit_code,
#                                 policy_number=row.get("policy_number"),
#                                 customer_name=row.get("customer_name"),

#                                 agent_code=row.get("agent_code"),
#                                 customer_code=row.get("customer_code"),

#                                 intermediary_name=row.get("intermediary_name"),
#                                 broker_name=row.get("broker_name"),

#                                 push_note_request_date=row.get("push_note_request_date"),

#                                 receipted_amount=row.get("receipted_amount"),
#                                 levies=row.get("levies"),
#                                 available_allocation=row.get("available_allocation"),

#                                 broker_commission=row.get("broker_commission"),
#                                 withholding_tax=row.get("withholding_tax"),
#                                 commission_payable=row.get("commission_payable"),

#                                 transaction_total_amount=row.get("transaction_total_amount"),
#                                 payment_status=row.get("payment_status"),

#                                 primarybenefitname=row.get("primarybenefitname"),
#                                 customerspolicycode=row.get("customerspolicycode"),
#                                 primarybenefitcode=row.get("primarybenefitcode"),
#                             )
#                         )

#                 if to_create:
#                     CommissionRecord.objects.bulk_create(to_create, batch_size=1000)

#                 if to_update:
#                     CommissionRecord.objects.bulk_update(
#                         to_update,
#                         [
#                             "push_note_code",
#                             "transaction_number",
#                             "policy_number",
#                             "customer_name",
#                             "agent_code",
#                             "customer_code",
#                             "intermediary_name",
#                             "broker_name",
#                             "push_note_request_date",
#                             "receipted_amount",
#                             "levies",
#                             "available_allocation",
#                             "broker_commission",
#                             "withholding_tax",
#                             "commission_payable",
#                             "transaction_total_amount",
#                             "payment_status",
#                             "primarybenefitname",
#                             "customerspolicycode",
#                             "primarybenefitcode",
#                             "updated_at",
#                         ],
#                         batch_size=1000
#                     )

#             # =========================================
#             # RESPONSE (PAGINATION)
#             # =========================================

#             paginator = PageNumberPagination()

#             paginated = paginator.paginate_queryset(results, request, view=self)

#             return paginator.get_paginated_response(paginated)

#         except Exception as e:
#             return Response(
#                 {"success": False, "error": str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )
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



# from django.utils import timezone
# from django.db import transaction
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status

# from django.utils import timezone
# from django.db import transaction
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status

# from .models import CommissionRecord

# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from django.db import transaction, connections
# from django.utils import timezone

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
                    WHERE pushnotedrcrnotenumber = ANY(%s)
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
