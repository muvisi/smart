from django.shortcuts import render
from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.db import connections, transaction
from datetime import datetime, timedelta
import pytz
from celery import shared_task

from commisions.models import CommissionAllocation

@shared_task
def alloc_commissions_task():

    tz = pytz.timezone("Africa/Nairobi")
    now = datetime.now(tz)

    today = now.date()
    day = today.day

    # ======================================================
    # 🚫 SCHEDULE RULES (YOUR BUSINESS LOGIC)
    # ======================================================

    # Skip 2nd, 3rd, 16th, 17th
    if day in [2, 3, 16, 17]:
        return f"Skipped due to restricted date: {day}"

    # Run ONLY at specific times
    hour = now.hour

    # Rule A: 1st & 15th at 11 PM
    if day in [1, 15] and hour != 23:
        return f"Skipped (must run at 11PM) day={day} hour={hour}"

    # Rule B: all other allowed days at 5 PM
    if day not in [1, 15] and hour != 17:
        return f"Skipped (must run at 5PM) day={day} hour={hour}"

    # ======================================================
    # DATABASE HELPERS
    # ======================================================

    def crud(action, sql):
        with connections['external_mssql'].cursor() as cursor:
            cursor.execute(sql)
            if action == "R":
                cols = [c[0] for c in cursor.description]
                return [dict(zip(cols, r)) for r in cursor.fetchall()]
            return "OK"

    allocations = []

    # ======================================================
    # GET RECEIPTS
    # ======================================================

    sqlreceipts = """
    select PREMIUM_RECEIPT.invoice_no,
           PREMIUM_RECEIPT.receipt_no,
           sum(PREMIUM_RECEIPT.receipt_amount) as receipt_amount
    from PREMIUM_RECEIPT
    where PREMIUM_RECEIPT.agent_id<>'54'
      and PREMIUM_RECEIPT.receipt_amount>0
      and PREMIUM_RECEIPT.receipt_date >= DATEADD(day,-15,GETDATE())
    group by PREMIUM_RECEIPT.invoice_no, PREMIUM_RECEIPT.receipt_no
    """

    receipts = crud("R", sqlreceipts)

    # ======================================================
    # ALLOCATION ENGINE
    # ======================================================

    for receipt in receipts:

        invoice_no = receipt["invoice_no"]
        receipt_no = receipt["receipt_no"]
        receipt_amount = float(receipt.get("receipt_amount") or 0)

        sqlAllocation = f"""
        select invoice_no,class,
               isnull(net_premium,0) as net_premium,
               isnull(allocated_amt,0) as allocated_amt
        from premium_invoice_details_sammary
        where allocated is null
        and invoice_no='{invoice_no}'
        """

        debits = crud("R", sqlAllocation)

        for debit in debits:

            class_ = debit["class"]
            net_premium = float(debit["net_premium"])
            allocated_amt = float(debit["allocated_amt"])

            all_amt = min(receipt_amount, net_premium - allocated_amt)

            if all_amt > 0:

                crud("U", f"""
                INSERT INTO premium_invoice_details_sammary
                (id_key, invoice_no, class, net_premium,
                 allocated, allocated_amt, receipt_no)
                VALUES (
                    (SELECT ISNULL(MAX(id_key),0)+1 FROM premium_invoice_details_sammary),
                    '{invoice_no}',
                    '{class_}',
                    NULL,
                    1,
                    '{all_amt}',
                    '{receipt_no}'
                )
                """)

                crud("U", f"""
                UPDATE PREMIUM_RECEIPT
                SET commis_paid='1'
                WHERE invoice_no='{invoice_no}'
                AND receipt_no='{receipt_no}'
                """)

                CommissionAllocation.objects.create(
                    invoice_no=invoice_no,
                    receipt_no=receipt_no,
                    class_name=class_,
                    allocated_amt=all_amt,
                    levied=0
                )

                allocations.append({
                    "invoice_no": invoice_no,
                    "receipt_no": receipt_no,
                    "class": class_,
                    "allocated_amt": all_amt
                })

    # ===============================
    # EMAIL REPORT
    # ===============================
    allocation_time = datetime.now().strftime("%d-%b-%Y")

    if allocations:

        table_rows = "".join(f"""
        <tr>
            <td>{a['invoice_no']}</td>
            <td>{a['receipt_no']}</td>
            <td>{a['class']}</td>
            <td style="text-align:right">{a['allocated_amt']:.2f}</td>
            <td style="text-align:right">{a['levied']:.2f}</td>
        </tr>
        """ for a in allocations)

        total_allocated = sum(a['allocated_amt'] for a in allocations)
        total_levied = sum(a['levied'] for a in allocations)

        totals_row = f"""
        <tr style="font-weight:bold;background:#e0e0e0;">
        <td colspan="3" style="text-align:center">TOTAL</td>
        <td style="text-align:right">{total_allocated:.2f}</td>
        <td style="text-align:right">{total_levied:.2f}</td>
        </tr>
        """

    else:

        table_rows = """
        <tr>
        <td colspan="5" style="text-align:center">No allocations done</td>
        </tr>
        """
        totals_row = ""

    html_content = f"""
    <html>
    <body style="font-family:Arial;background:#f5f5f5;padding:20px;">

    <div style="background:#4a4a4a;color:white;padding:10px;text-align:center;">
    <h2>Madison Group - Daily Commission Allocation Report</h2>
    <p>Dated: {allocation_time}</p>
    </div>

    <div style="background:white;padding:15px;margin-top:10px;border-radius:5px;">
    <table border="1" cellpadding="5" cellspacing="0" width="100%" style="border-collapse:collapse;">
    <thead style="background:#e0e0e0;">
    <tr>
    <th>Invoice</th>
    <th>Receipt</th>
    <th>Class</th>
    <th>Allocated</th>
    <th>Levied</th>
    </tr>
    </thead>

    <tbody>
    {table_rows}
    {totals_row}
    </tbody>

    </table>
    </div>

    <div style="background:#d3d3d3;padding:10px;margin-top:10px;text-align:center;">
    <p>Developer: Samuel Mwangangi</p>
    <p><em>Disclaimer: No defending systems, we make them work!</em></p>
    </div>

    </body>
    </html>
    """

    email = EmailMessage(
        subject="Madison Group - Daily Allocation Report",
        body=html_content,
        from_email="Madison Notifications <haisnotifications@madison.co.ke>",
        to=[
            "samuel.mwangangi@madison.co.ke",
            "mwangangimuvisi@gmail.com",
            "paulyne.mukhanyi@madison.co.ke",
            "ict@madison.co.ke"
        ],
    )

    email.content_subtype = "html"
    email.send()


    EmailMessage(
        subject="Daily Allocation Report",
        body=f"Completed allocations: {len(allocations)}",
        to=["ict@madison.co.ke"]
    ).send()

    return {
        "success": True,
        "allocations": len(allocations),
        "date": str(today)
    }