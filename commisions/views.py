from django.shortcuts import render
from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.db import connections, transaction
import calendar
from datetime import datetime, timedelta
from email.mime.image import MIMEImage
from pathlib import Path
import pytz

from .models import CommissionAllocation

LOGO_PATH = Path(__file__).resolve().parent / "logo.jpeg"
LOGO_CID = "madison_logo"


def attach_madison_logo(email):
    if not LOGO_PATH.exists():
        return

    with LOGO_PATH.open("rb") as logo_file:
        logo = MIMEImage(logo_file.read(), _subtype="jpeg")
        logo.add_header("Content-ID", f"<{LOGO_CID}>")
        logo.add_header("Content-Disposition", "inline", filename="logo.jpeg")
        email.attach(logo)


def ordinal_day(day):
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def get_allocation_period(run_date):
    month_name = run_date.strftime("%B")
    month_end = calendar.monthrange(run_date.year, run_date.month)[1]

    if run_date.day <= 15:
        return f"{month_name} Batch 1", "1st - 15th"

    return f"{month_name} Batch 2", f"15th - {ordinal_day(month_end)}"

# @shared_task
# def alloc_commissions_task():

#     tz = pytz.timezone("Africa/Nairobi")
#     now = datetime.now(tz)

#     today = now.date()
#     day = today.day

#     # ======================================================
#     # 🚫 SCHEDULE RULES (YOUR BUSINESS LOGIC)
#     # ======================================================

#     # Skip 2nd, 3rd, 16th, 17th
#     if day in [2, 3, 16, 17]:
#         return f"Skipped due to restricted date: {day}"

#     # Run ONLY at specific times
#     hour = now.hour

#     # Rule A: 1st & 15th at 11 PM
#     if day in [1, 15] and hour != 23:
#         return f"Skipped (must run at 11PM) day={day} hour={hour}"

#     # Rule B: all other allowed days at 5 PM
#     if day not in [1, 15] and hour != 17:
#         return f"Skipped (must run at 5PM) day={day} hour={hour}"

#     # ======================================================
#     # DATABASE HELPERS
#     # ======================================================

#     def crud(action, sql):
#         with connections['external_mssql'].cursor() as cursor:
#             cursor.execute(sql)
#             if action == "R":
#                 cols = [c[0] for c in cursor.description]
#                 return [dict(zip(cols, r)) for r in cursor.fetchall()]
#             return "OK"

#     allocations = []

#     # ======================================================
#     # GET RECEIPTS
#     # ======================================================

#     sqlreceipts = """
#     select PREMIUM_RECEIPT.invoice_no,
#            PREMIUM_RECEIPT.receipt_no,
#            sum(PREMIUM_RECEIPT.receipt_amount) as receipt_amount
#     from PREMIUM_RECEIPT
#     where PREMIUM_RECEIPT.agent_id<>'54'
#       and PREMIUM_RECEIPT.receipt_amount>0
#       and PREMIUM_RECEIPT.receipt_date >= DATEADD(day,-15,GETDATE())
#     group by PREMIUM_RECEIPT.invoice_no, PREMIUM_RECEIPT.receipt_no
#     """

#     receipts = crud("R", sqlreceipts)

#     # ======================================================
#     # ALLOCATION ENGINE
#     # ======================================================

#     for receipt in receipts:

#         invoice_no = receipt["invoice_no"]
#         receipt_no = receipt["receipt_no"]
#         receipt_amount = float(receipt.get("receipt_amount") or 0)

#         sqlAllocation = f"""
#         select invoice_no,class,
#                isnull(net_premium,0) as net_premium,
#                isnull(allocated_amt,0) as allocated_amt
#         from premium_invoice_details_sammary
#         where allocated is null
#         and invoice_no='{invoice_no}'
#         """

#         debits = crud("R", sqlAllocation)

#         for debit in debits:

#             class_ = debit["class"]
#             net_premium = float(debit["net_premium"])
#             allocated_amt = float(debit["allocated_amt"])

#             all_amt = min(receipt_amount, net_premium - allocated_amt)

#             if all_amt > 0:

#                 crud("U", f"""
#                 INSERT INTO premium_invoice_details_sammary
#                 (id_key, invoice_no, class, net_premium,
#                  allocated, allocated_amt, receipt_no)
#                 VALUES (
#                     (SELECT ISNULL(MAX(id_key),0)+1 FROM premium_invoice_details_sammary),
#                     '{invoice_no}',
#                     '{class_}',
#                     NULL,
#                     1,
#                     '{all_amt}',
#                     '{receipt_no}'
#                 )
#                 """)

#                 crud("U", f"""
#                 UPDATE PREMIUM_RECEIPT
#                 SET commis_paid='1'
#                 WHERE invoice_no='{invoice_no}'
#                 AND receipt_no='{receipt_no}'
#                 """)

#                 CommissionAllocation.objects.create(
#                     invoice_no=invoice_no,
#                     receipt_no=receipt_no,
#                     class_name=class_,
#                     allocated_amt=all_amt,
#                     levied=0
#                 )

#                 allocations.append({
#                     "invoice_no": invoice_no,
#                     "receipt_no": receipt_no,
#                     "class": class_,
#                     "allocated_amt": all_amt
#                 })

#     # ===============================
#     # EMAIL REPORT
#     # ===============================
#     allocation_time = datetime.now().strftime("%d-%b-%Y")

#     if allocations:

#         table_rows = "".join(f"""
#         <tr>
#             <td>{a['invoice_no']}</td>
#             <td>{a['receipt_no']}</td>
#             <td>{a['class']}</td>
#             <td style="text-align:right">{a['allocated_amt']:.2f}</td>
#             <td style="text-align:right">{a['levied']:.2f}</td>
#         </tr>
#         """ for a in allocations)

#         total_allocated = sum(a['allocated_amt'] for a in allocations)
#         total_levied = sum(a['levied'] for a in allocations)

#         totals_row = f"""
#         <tr style="font-weight:bold;background:#e0e0e0;">
#         <td colspan="3" style="text-align:center">TOTAL</td>
#         <td style="text-align:right">{total_allocated:.2f}</td>
#         <td style="text-align:right">{total_levied:.2f}</td>
#         </tr>
#         """

#     else:

#         table_rows = """
#         <tr>
#         <td colspan="5" style="text-align:center">No allocations done</td>
#         </tr>
#         """
#         totals_row = ""

#     html_content = f"""
#     <html>
#     <body style="font-family:Arial;background:#f5f5f5;padding:20px;">

#     <div style="background:#4a4a4a;color:white;padding:10px;text-align:center;">
#     <h2>Madison Group - Daily Commission Allocation Report</h2>
#     <p>Dated: {allocation_time}</p>
#     </div>

#     <div style="background:white;padding:15px;margin-top:10px;border-radius:5px;">
#     <table border="1" cellpadding="5" cellspacing="0" width="100%" style="border-collapse:collapse;">
#     <thead style="background:#e0e0e0;">
#     <tr>
#     <th>Invoice</th>
#     <th>Receipt</th>
#     <th>Class</th>
#     <th>Allocated</th>
#     <th>Levied</th>
#     </tr>
#     </thead>

#     <tbody>
#     {table_rows}
#     {totals_row}
#     </tbody>

#     </table>
#     </div>

#     <div style="background:#d3d3d3;padding:10px;margin-top:10px;text-align:center;">
#     <p>Developer: Samuel Mwangangi</p>
#     <p><em>Disclaimer: No defending systems, we make them work!</em></p>
#     </div>

#     </body>
#     </html>
#     """

#     email = EmailMessage(
#         subject="Madison Group - Daily Allocation Report",
#         body=html_content,
#         from_email="Madison Notifications <haisnotifications@madison.co.ke>",
#         to=[
#             "samuel.mwangangi@madison.co.ke",
#             "mwangangimuvisi@gmail.com",
#             "paulyne.mukhanyi@madison.co.ke",
#             "ict@madison.co.ke"
#         ],
#     )

#     email.content_subtype = "html"
#     email.send()


#     EmailMessage(
#         subject="Daily Allocation Report",
#         body=f"Completed allocations: {len(allocations)}",
#         to=["ict@madison.co.ke"]
#     ).send()

#     return {
#         "success": True,
#         "allocations": len(allocations),
#         "date": str(today)
#     }
@transaction.atomic(using='external_mssql')
def alloc_commissions(request):
    """
    Allocate premiums from receipts to invoices safely in one transaction.
    Logs allocations in Django model and sends an email report.
    """

    tz = pytz.timezone("Africa/Nairobi")
    today = datetime.now(tz).date()
    thisYr = today - timedelta(days=15)

    # ===============================
    # DATABASE HELPER
    # ===============================
    def crud(action, sql):
        with connections['external_mssql'].cursor() as cursor:
            cursor.execute(sql)
            if action == "R":
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            return "OK"

    def wh_log(msg):
        print(msg)

    # ===============================
    # GET RECEIPTS
    # ===============================
    if "invoice_no" in request.GET:
        invoNo = request.GET.get("invoice_no").strip()

        sqlreceipts = f"""
        select PREMIUM_RECEIPT.invoice_no,
               PREMIUM_RECEIPT.receipt_no,
               sum(PREMIUM_RECEIPT.receipt_amount) as receipt_amount
        from PREMIUM_RECEIPT
        where PREMIUM_RECEIPT.agent_id<>'54'
        and premium_receipt.invoice_no in ('{invoNo}')
        group by PREMIUM_RECEIPT.invoice_no, PREMIUM_RECEIPT.receipt_no
        """

    else:
        sqlreceipts = f"""
        select PREMIUM_RECEIPT.invoice_no,
               PREMIUM_RECEIPT.receipt_no,
               sum(PREMIUM_RECEIPT.receipt_amount) as receipt_amount
        from PREMIUM_RECEIPT
        where PREMIUM_RECEIPT.agent_id<>'54'
        and PREMIUM_RECEIPT.receipt_amount>0
        and PREMIUM_RECEIPT.receipt_date between '{thisYr}' and '{today}'
        group by PREMIUM_RECEIPT.invoice_no, PREMIUM_RECEIPT.receipt_no
        order by PREMIUM_RECEIPT.receipt_no desc
        """

    receipts = crud("R", sqlreceipts)

    allocations = []

    # ===============================
    # ALLOCATION LOOP
    # ===============================
    for receipt in receipts:

        receipt_no = receipt["receipt_no"]
        invoice_no = receipt["invoice_no"]
        receipt_amount = float(receipt.get("receipt_amount") or 0)

        sqlAllocation = f"""
        with a as (
            select invoice_no,class,isnull(net_premium,0) as net_premium,
                   allocated,isnull(allocated_amt,0) as allocated_amt,
                   levied,receipt_no
            from premium_invoice_details_sammary
            where allocated is null
        ),
        b as (
            select invoice_no,class,allocated,
                   sum(isnull(allocated_amt,0)) as allocated_amt,
                   sum(isnull(levied,0)) as levied
            from premium_invoice_details_sammary
            where allocated=1
            group by invoice_no,class,allocated
        )
        select a.invoice_no,a.class,isnull(a.net_premium,0) as net_premium,
               b.allocated,isnull(b.allocated_amt,0) as allocated_amt,
               isnull(b.levied,0) as levied
        from a
        left outer join b
        on a.invoice_no=b.invoice_no and a.class=b.class
        where isnull(b.allocated_amt,0)<a.net_premium
        and a.invoice_no='{invoice_no}'
        """

        unAllocatedDebits = crud("R", sqlAllocation)

        if not unAllocatedDebits:
            continue

        for debit in unAllocatedDebits:

            class_ = debit["class"]
            net_premium = float(debit.get("net_premium") or 0)
            allocated_amt = float(debit.get("allocated_amt") or 0)

            # ===============================
            # GET LEVIES
            # ===============================
            sqlLevy = f"""
            select invoice_no,
                   isnull(stamp_duty,0) sd,
                   isnull(tl,0) tl,
                   isnull(phcf,0) phcf
            from PREMIUM_INVOICE
            where invoice_no='{invoice_no}'
            """

            Levies = crud("R", sqlLevy)

            premLevies = sum(
                float(levy.get("sd") or 0) +
                float(levy.get("tl") or 0) +
                float(levy.get("phcf") or 0)
                for levy in Levies
            )

            # ===============================
            # CURRENT RECEIPT ALLOCATIONS
            # ===============================
            sqLRctAllocation = f"""
            select invoice_no,
                   sum(isnull(allocated_amt,0)) as alloc_amt,
                   sum(isnull(levied,0)) as levy_amt,
                   (sum(isnull(allocated_amt,0))+sum(isnull(levied,0))) as T_allocated_amt
            from premium_invoice_details_sammary
            where allocated=1
            and invoice_no='{invoice_no}'
            and receipt_no='{receipt_no}'
            group by invoice_no
            """

            leviedAmounts = crud("R", sqLRctAllocation)

            alloc_amt_rec = 0
            t_allocate_rec = 0

            for la in leviedAmounts:
                alloc_amt_rec = float(la.get("alloc_amt") or 0)
                t_allocate_rec = float(la.get("T_allocated_amt") or 0)

            # ===============================
            # LEVY DEDUCTIONS
            # ===============================
            sqlLevyDeductions = f"""
            select sum(isnull(levied,0)) as levied
            from premium_invoice_details_sammary
            where allocated=1
            and invoice_no='{invoice_no}'
            """

            leviedDeductions = crud("R", sqlLevyDeductions)

            allLevy = sum(float(ld.get("levied") or 0) for ld in leviedDeductions)

            levied = round(premLevies - allLevy, 2) if premLevies != allLevy else 0

            # ===============================
            # ALLOCATION CALCULATION
            # ===============================
            if receipt_amount > levied:

                receipt_bal = receipt_amount - t_allocate_rec - levied
                unallocated_amt = net_premium - allocated_amt

                all_amt = min(receipt_bal, unallocated_amt)

                if all_amt > 0:

                    all_amt = round(min(all_amt, net_premium), 2)

                    # ===============================
                    # INSERT INTO MSSQL
                    # ===============================
                    crud("U", f"""
                    INSERT INTO premium_invoice_details_sammary
                    (id_key, invoice_no, class, net_premium,
                     allocated, allocated_amt, levied, receipt_no)
                    values(
                        (select max(id_key)+1 from premium_invoice_details_sammary),
                        '{invoice_no}','{class_}',NULL,1,
                        '{all_amt}','{levied}','{receipt_no}'
                    )
                    """)

                    crud("U", f"""
                    update PREMIUM_RECEIPT
                    set commis_paid='1'
                    where invoice_no='{invoice_no}'
                    and receipt_no='{receipt_no}'
                    """)

                    # ===============================
                    # SAVE LOG TO DJANGO MODEL
                    # ===============================
                    CommissionAllocation.objects.create(
                        invoice_no=invoice_no,
                        receipt_no=receipt_no,
                        class_name=class_,
                        allocated_amt=all_amt,
                        levied=levied
                    )

                    wh_log(f"{receipt_no} Allocated Successfully to {invoice_no}")

                    allocations.append({
                        "invoice_no": invoice_no,
                        "receipt_no": receipt_no,
                        "class": class_,
                        "allocated_amt": all_amt,
                        "levied": levied
                    })

    # ===============================
    # EMAIL REPORT
    # ===============================
    report_now = datetime.now()
    allocation_time = report_now.strftime("%d-%b-%Y")
    period_name, period_range = get_allocation_period(report_now)
    copyright_year = report_now.year
    total_allocated = sum(a["allocated_amt"] for a in allocations)
    total_levied = sum(a["levied"] for a in allocations)
    allocation_count = len(allocations)

    if allocations:

        table_rows = "".join(f"""
        <tr style="border-bottom:1px solid #e8edf3;">
            <td style="padding:13px 16px;color:#1f2937;font-size:13px;">{a['invoice_no']}</td>
            <td style="padding:13px 16px;color:#1f2937;font-size:13px;">{a['receipt_no']}</td>
            <td style="padding:13px 16px;color:#1f2937;font-size:13px;">{a['class']}</td>
            <td style="padding:13px 16px;color:#0f766e;font-size:13px;font-weight:700;text-align:right;">{a['allocated_amt']:,.2f}</td>
            <td style="padding:13px 16px;color:#475569;font-size:13px;text-align:right;">{a['levied']:,.2f}</td>
        </tr>
        """ for a in allocations)

        totals_row = f"""
        <tr style="background:#f8fafc;font-weight:700;">
        <td colspan="3" style="padding:14px 16px;color:#0f172a;text-align:right;">TOTAL</td>
        <td style="padding:14px 16px;color:#0f766e;text-align:right;">{total_allocated:,.2f}</td>
        <td style="padding:14px 16px;color:#475569;text-align:right;">{total_levied:,.2f}</td>
        </tr>
        """

    else:

        table_rows = """
        <tr>
        <td colspan="5" style="padding:28px 16px;color:#64748b;text-align:center;">No allocations were processed for this run.</td>
        </tr>
        """
        totals_row = ""

    html_content = f"""
    <!doctype html>
    <html>
    <body style="margin:0;background:#eef3f8;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef3f8;padding:28px 12px;">
    <tr>
    <td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:820px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 12px 34px rgba(15,23,42,0.12);">
    <tr>
    <td style="background:#002f6c;padding:24px 28px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
    <td style="vertical-align:middle;">
    <img src="cid:{LOGO_CID}" alt="Madison Group" width="150" style="display:block;max-width:150px;height:auto;background:#ffffff;border-radius:10px;padding:8px;">
    </td>
    <td align="right" style="vertical-align:middle;color:#dbeafe;font-size:13px;">
    <div style="font-weight:700;color:#ffffff;font-size:14px;">Commission Allocation</div>
    <div>{allocation_time}</div>
    <div style="margin-top:8px;display:inline-block;background:#ffffff;color:#002f6c;border-radius:999px;padding:7px 12px;font-size:12px;font-weight:800;">{period_name}: {period_range}</div>
    </td>
    </tr>
    </table>
    <div style="padding-top:26px;">
    <h1 style="margin:0;color:#ffffff;font-size:26px;line-height:1.25;font-weight:800;">Daily Commission Allocation Report</h1>
    <p style="margin:8px 0 0;color:#cfe2ff;font-size:14px;line-height:1.6;">Allocation run completed for <strong style="color:#ffffff;">{period_name}</strong>, covering {period_range}.</p>
    </div>
    </td>
    </tr>
    <tr>
    <td style="padding:24px 28px 10px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
    <td style="width:25%;padding:0 8px 12px 0;">
    <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:16px;">
    <div style="font-size:12px;color:#9a3412;text-transform:uppercase;font-weight:700;">Period</div>
    <div style="margin-top:8px;font-size:18px;line-height:1.25;font-weight:800;color:#7c2d12;">{period_name}</div>
    <div style="margin-top:4px;font-size:12px;color:#9a3412;">{period_range}</div>
    </div>
    </td>
    <td style="width:25%;padding:0 8px 12px 0;">
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px;">
    <div style="font-size:12px;color:#64748b;text-transform:uppercase;font-weight:700;">Allocations</div>
    <div style="margin-top:8px;font-size:24px;font-weight:800;color:#0f172a;">{allocation_count}</div>
    </div>
    </td>
    <td style="width:25%;padding:0 4px 12px;">
    <div style="background:#ecfdf5;border:1px solid #bbf7d0;border-radius:12px;padding:16px;">
    <div style="font-size:12px;color:#047857;text-transform:uppercase;font-weight:700;">Allocated Amount</div>
    <div style="margin-top:8px;font-size:24px;font-weight:800;color:#065f46;">{total_allocated:,.2f}</div>
    </div>
    </td>
    <td style="width:25%;padding:0 0 12px 8px;">
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px;">
    <div style="font-size:12px;color:#64748b;text-transform:uppercase;font-weight:700;">Levies</div>
    <div style="margin-top:8px;font-size:24px;font-weight:800;color:#334155;">{total_levied:,.2f}</div>
    </div>
    </td>
    </tr>
    </table>
    </td>
    </tr>
    <tr>
    <td style="padding:8px 28px 28px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
    <thead>
    <tr style="background:#f1f5f9;">
    <th align="left" style="padding:13px 16px;color:#334155;font-size:12px;text-transform:uppercase;">Invoice</th>
    <th align="left" style="padding:13px 16px;color:#334155;font-size:12px;text-transform:uppercase;">Receipt</th>
    <th align="left" style="padding:13px 16px;color:#334155;font-size:12px;text-transform:uppercase;">Class</th>
    <th align="right" style="padding:13px 16px;color:#334155;font-size:12px;text-transform:uppercase;">Allocated</th>
    <th align="right" style="padding:13px 16px;color:#334155;font-size:12px;text-transform:uppercase;">Levied</th>
    </tr>
    </thead>
    <tbody>
    {table_rows}
    {totals_row}
    </tbody>
    </table>
    </td>
    </tr>
    <tr>
    <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:18px 28px;text-align:center;color:#64748b;font-size:12px;line-height:1.6;">
    <div style="font-weight:700;color:#334155;">Copyright &copy; {copyright_year} Madison Group. All rights reserved.</div>
    <div>Automated by E. Samuel</div>
    </td>
    </tr>
    </table>
    </td>
    </tr>
    </table>
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
    attach_madison_logo(email)
    email.send()

    return JsonResponse({
        "message": "Allocation completed",
        "allocations": allocations
    })
