from datetime import date
from decimal import Decimal
from django.db import connections
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from . import services

class CommissionAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        task = request.query_params.get('task','pay').lower()
        try:
            if task == 'agents':
                with connections[services.DB].cursor() as cur:
                    cur.execute('SELECT agent_id,agent_name FROM agent ORDER BY agent_name')
                    return Response([{'id':x,'name':y} for x,y in cur.fetchall()])
            if task == 'pay':
                start = date.fromisoformat(request.query_params['dateFrom'])
                end = date.fromisoformat(request.query_params['dateTo'])
                if end < start: return Response({'error':'dateTo precedes dateFrom'},status=400)
                agent = request.query_params.get('agentId')
                if agent and agent.lower() != 'all': agent = int(agent)
                else: agent = None
                return Response(services.commission_preview(services.eligible_rows(start,end,agent)))
            if task == 'vouchers': return Response(services.vouchers())
            if task == 'voucher': return Response(services.voucher_detail(request.query_params['voucherNo']))
            if task == 'cheques': return Response(services.cheques())
            if task == 'cheque': return Response(services.cheque_detail(request.query_params['paymentNo']))
            return Response({'error':'Invalid task'},status=400)
        except (KeyError,ValueError) as exc:
            return Response({'error':str(exc)},status=400)

    def post(self, request):
        return Response({'error':'Financial writes are not enabled until the legacy voucher/payment number generator, approval rules, and exact commission cap basis have been verified. See MIGRATION_NOTES.md.'},status=status.HTTP_501_NOT_IMPLEMENTED)
from django.db import connections, DatabaseError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status


class CommissionAgentsAPIView(APIView):
    """Return HAIS intermediaries/agents from the existing SQL Server AGENT table."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            with connections["external_mssql"].cursor() as cursor:
                cursor.execute("""
                    SELECT AGENT_ID, AGENT_NAME
                    FROM AGENT
                    ORDER BY AGENT_NAME ASC
                """)
                agents = [
                    {"agent_id": row[0], "agent_name": row[1]}
                    for row in cursor.fetchall()
                ]
            return Response({"count": len(agents), "results": agents})
        except DatabaseError:
            return Response(
                {"error": "Unable to retrieve agents."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
