"""SQL Server commission services. Legacy tables; no schema migrations."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import connections

DB = "external_mssql"
CENT = Decimal("0.01")
ZERO = Decimal("0")


def money(value):
    return Decimal(str(value if value is not None else 0)).quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def fetch_dicts(cursor):
    columns = [column[0].lower() for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# CTE is a single valid T-SQL statement. The date parameters are applied in
# the outer SELECT (not inside the CTEs), so the backend's GROUP BY parameter
# rewriting cannot shift them. This query is read-only.
ELIGIBLE_SQL = """
;WITH inv AS (
    SELECT pi.invoice_no, pi.agent_id, a.agent_name,
           a.commiss_rate, a.whtx_rate, pi.corp_id, pi.member_no,
           pi.invoice_net,
           COALESCE((
               SELECT SUM(COALESCE(cr.invoice_net, 0))
               FROM premium_invoice cr
               WHERE cr.related_to = pi.invoice_no
           ), 0) AS credit_net
    FROM premium_invoice pi
    INNER JOIN agent a ON a.agent_id = pi.agent_id
    WHERE pi.agent_id <> 54 AND pi.related_to IS NULL
), receipts AS (
    SELECT invoice_no, SUM(COALESCE(receipt_amount, 0)) AS receipt_amt
    FROM premium_receipt
    GROUP BY invoice_no
), eligible_details AS (
    SELECT p.id_key, p.invoice_no, p.class, p.receipt_no,
           p.net_premium, p.allocated_amt, p.levied,
           p.allocated, p.paid, p.cv_authorized, b.benefit
    FROM premium_invoice_details_sammary p
    INNER JOIN benefit b ON b.code = p.class
    WHERE COALESCE(p.allocated, 0) = 1
      AND COALESCE(p.paid, 0) = 0
      AND COALESCE(p.cv_authorized, 0) = 0
)
SELECT r.*, i.agent_id, i.agent_name, i.commiss_rate, i.whtx_rate,
       i.corp_id, i.member_no, i.invoice_net, i.credit_net,
       COALESCE(rec.receipt_amt, 0) AS receipt_amt,
       COALESCE(c.corporate, '') AS corporate
FROM eligible_details r
INNER JOIN inv i ON i.invoice_no = r.invoice_no
INNER JOIN receipts rec ON rec.invoice_no = r.invoice_no
LEFT JOIN corporate c ON c.corp_id = i.corp_id
WHERE COALESCE(rec.receipt_amt, 0) + 1 >= i.invoice_net + i.credit_net
  AND EXISTS (
      SELECT 1 FROM premium_receipt pr
      WHERE pr.invoice_no = r.invoice_no
        AND pr.receipt_date >= %s
        AND pr.receipt_date < %s
  )
"""


def _allocate_caps(rows):
    """Cap unpaid commissionable allocations per invoice, net of levies.

    Reserve the allocated-minus-levy base on previously paid rows. This is
    intentionally conservative for historical data and requires reconciliation
    before enabling financial writes.
    """
    invoice_ids = sorted({str(row["invoice_no"]) for row in rows})
    if not invoice_ids:
        return []

    # SQL Server limits query parameters to 2100. Batch for large date ranges.
    paid_bases = {}
    for offset in range(0, len(invoice_ids), 1000):
        batch = invoice_ids[offset:offset + 1000]
        placeholders = ",".join(["%s"] * len(batch))
        sql = f"""
            SELECT invoice_no,
                   SUM(CASE WHEN COALESCE(paid, 0) = 1 THEN
                       CASE WHEN COALESCE(allocated_amt, 0) - COALESCE(levied, 0) > 0
                            THEN COALESCE(allocated_amt, 0) - COALESCE(levied, 0)
                            ELSE 0 END
                       ELSE 0 END) AS paid_base
            FROM premium_invoice_details_sammary
            WHERE invoice_no IN ({placeholders})
            GROUP BY invoice_no
        """
        with connections[DB].cursor() as cursor:
            cursor.execute(sql, batch)
            paid_bases.update({str(invoice): money(base) for invoice, base in cursor.fetchall()})

    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row["invoice_no"])].append(row)

    output = []
    for invoice_no, group in grouped.items():
        remaining = max(
            money(group[0]["invoice_net"])
            + money(group[0]["credit_net"])
            - paid_bases.get(invoice_no, ZERO),
            ZERO,
        )
        for row in sorted(group, key=lambda item: str(item["id_key"])):
            eligible = max(money(row["allocated_amt"]) - money(row["levied"]), ZERO)
            base = min(eligible, remaining)
            remaining -= base
            rate = Decimal(str(row["commiss_rate"] or 0))
            tax_rate = Decimal(str(row["whtx_rate"] or 0))
            gross = money(base * rate / 100)
            tax = money(gross * tax_rate / 100)
            item = dict(row)
            item.update(
                commissionable_base=base,
                gross_commission=gross,
                withholding_tax=tax,
                net_commission=gross - tax,
            )
            output.append(item)
    return output


def eligible_rows(date_from, date_to, agent_id=None):
    if date_to < date_from:
        raise ValueError("dateTo precedes dateFrom")
    params = [date_from, date_to + timedelta(days=1)]
    sql = ELIGIBLE_SQL
    if agent_id is not None:
        sql += " AND i.agent_id = %s"
        params.append(agent_id)
    sql += " ORDER BY i.agent_name, r.invoice_no, r.id_key"
    with connections[DB].cursor() as cursor:
        cursor.execute(sql, params)
        rows = fetch_dicts(cursor)
    return _allocate_caps(rows)


def commission_preview(rows):
    return {
        "rows": rows,
        "totals": {
            "gross": sum((row["gross_commission"] for row in rows), ZERO),
            "withholding": sum((row["withholding_tax"] for row in rows), ZERO),
            "net": sum((row["net_commission"] for row in rows), ZERO),
        },
    }


def vouchers():
    with connections[DB].cursor() as cursor:
        cursor.execute("""
            SELECT commis_vno, COUNT(*) AS line_count,
                   SUM(COALESCE(commission, 0)) AS gross_commission,
                   SUM(COALESCE(wh_tax, 0)) AS withholding_tax
            FROM premium_invoice_details_sammary
            WHERE commis_vno IS NOT NULL AND commis_payno IS NOT NULL
            GROUP BY commis_vno ORDER BY commis_vno DESC
        """)
        return fetch_dicts(cursor)


def voucher_detail(voucher_no):
    with connections[DB].cursor() as cursor:
        cursor.execute("""
            SELECT p.id_key, p.invoice_no, p.class, p.allocated_amt,
                   p.commis_vno, p.commis_rate, p.wh_tax_rate,
                   p.wh_tax, p.commission, p.paid, b.benefit
            FROM premium_invoice_details_sammary p
            LEFT JOIN benefit b ON b.code = p.class
            WHERE p.commis_vno = %s
            ORDER BY p.invoice_no, p.id_key
        """, [voucher_no])
        return fetch_dicts(cursor)


def cheques():
    with connections[DB].cursor() as cursor:
        cursor.execute("""
            SELECT payment_no, cheque_no, cheque_date, cheque_amount,
                   deduction, total_commission
            FROM cheque_payment
            WHERE payee_type = 1
            ORDER BY payment_no DESC
        """)
        return fetch_dicts(cursor)


def cheque_detail(payment_no):
    with connections[DB].cursor() as cursor:
        cursor.execute("""
            SELECT p.id_key, p.invoice_no, p.class, p.net_premium,
                   p.allocated, p.allocated_amt, p.paid, p.commission,
                   p.commis_vno, p.commis_payno, p.wh_tax,
                   p.commis_rate, p.wh_tax_rate,
                   i.member_no, c.corporate, b.benefit
            FROM premium_invoice_details_sammary p
            JOIN premium_invoice i ON i.invoice_no = p.invoice_no
            LEFT JOIN corporate c ON c.corp_id = i.corp_id
            LEFT JOIN benefit b ON b.code = p.class
            WHERE p.commis_payno = %s
            ORDER BY p.invoice_no, p.id_key
        """, [payment_no])
        return fetch_dicts(cursor)

# Financial write operations are disabled until legacy sequence and
# authorization mappings are verified.
