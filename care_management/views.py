from datetime import datetime
from math import ceil
from uuid import uuid4
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from django.db import connections
from django.http import FileResponse, Http404
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .exports import ensure_care_management_export_dir, get_care_management_export_dir


BENEFIT_EXPRESSION = """
COALESCE(
    NULLIF(BTRIM(lba.lou_benefit_amount_sbenefit_na), ''),
    NULLIF(BTRIM(lba.lou_benefit_amount_pbenefit_na), '')
)
"""

SHASHIF_TYPE_EXPRESSION = """
CASE
    WHEN BTRIM(l.lou_shashif_type) = 'B' THEN 'BED REBATE'
    WHEN BTRIM(l.lou_shashif_type) = 'S' THEN 'SURGICAL PACKAGES'
    ELSE NULL
END
"""

LOU_STATUS_REPORT_QUERY = f"""
SELECT
    UPPER(l.lou_pre_auth_status_name) AS "admissionStatus",
    c.customernamebytype AS "customerName",
    l.lou_customer_member_name AS "memberName",
    l.lou_customer_member_numberchar AS "memberNumber",
    l.lou_reference_number AS "referenceNumber",
    l.lou_provider_name AS "providerName",
    lba.benefit AS "benefit",
    TO_CHAR(l.lou_creation_date, 'YYYY-MM-DD') AS "dateAuthorised",
    TO_CHAR(l.lou_discharge_date, 'YYYY-MM-DD') AS "dischargeDate",
    l.lou_lengh_of_stay AS "lengthOfStay",
    ld."diagnosisName" AS "diagnosisName",
    l.lou_notes AS "louNotes",
    l.lou_total_amount AS "reserveAmount",
    l.lou_discount_amount AS "discountAmount",
    {SHASHIF_TYPE_EXPRESSION} AS "shashifType",
    l.lou_shashif_amount AS "louShashifAmount"
FROM public.lou l
JOIN public.customers c
    ON l.lou_customer_code = c.customerscode
JOIN (
    SELECT
        benefit_rows.lou_code,
        STRING_AGG(
            DISTINCT benefit_rows.benefit,
            ', '
            ORDER BY benefit_rows.benefit
        ) AS benefit
    FROM (
        SELECT
            lba_inner.lou_benefit_amount_lou_code AS lou_code,
            COALESCE(
                NULLIF(BTRIM(lba_inner.lou_benefit_amount_sbenefit_na), ''),
                NULLIF(BTRIM(lba_inner.lou_benefit_amount_pbenefit_na), '')
            ) AS benefit
        FROM public.lou_benefit_amount lba_inner
        WHERE lba_inner.lou_benefit_amount_total_amoun > 0
    ) benefit_rows
    GROUP BY benefit_rows.lou_code
) lba
    ON l.lou_code = lba.lou_code
LEFT JOIN (
    SELECT
        lou_code,
        STRING_AGG(
            DISTINCT NULLIF(BTRIM(lou_diagnosisname), ''),
            ', '
        ) AS "diagnosisName"
    FROM public.loudiagnosis
    GROUP BY lou_code
) ld
    ON l.lou_code = ld.lou_code
"""

FOLLOW_UP_TYPE_EXPRESSION = """
CASE
    WHEN UPPER(BTRIM(cfi.caselou_followup_type)) = 'P' THEN 'Physical Location'
    WHEN UPPER(BTRIM(cfi.caselou_followup_type)) = 'V' THEN 'Virtual'
    ELSE cfi.caselou_followup_type
END
"""

FOLLOW_UP_REPORT_QUERY = f"""
SELECT
    cfi.caselou_code AS "caseLouCode",
    UPPER(l.lou_pre_auth_status_name) AS "admissionStatus",
    c.customernamebytype AS "corporate",
    l.lou_customer_member_name AS "memberName",
    l.lou_customer_member_numberchar AS "memberNumber",
    l.lou_reference_number AS "referenceNumber",
    l.lou_provider_name AS "providerName",
    lba.benefit AS "benefit",
    TO_CHAR(l.lou_creation_date, 'YYYY-MM-DD') AS "dateAuthorised",
    TO_CHAR(l.lou_service_date, 'YYYY-MM-DD') AS "dateAdmitted",
    l.lou_total_amount AS "amountAuthorised",
    TO_CHAR(l.lou_discharge_date, 'YYYY-MM-DD') AS "dischargeDate",
    l.lou_lengh_of_stay AS "lengthOfStay",
    ld."diagnosisName" AS "diagnosisName",
    l.lou_notes AS "louNotes",
    cfi.caselou_followup_current_activ AS "currentActiveManagement",
    cfi.caselou_followup_notes AS "notes",
    cfi.caselou_followup_exclusion_non AS "exclusionOrNonPayables",
    cfi.caselou_followup_interim_bill_ AS "interimBill",
    TO_CHAR(cfi.caselou_followup_date, 'YYYY-MM-DD') AS "followUpDate",
    {FOLLOW_UP_TYPE_EXPRESSION} AS "followUpType"
FROM (
    SELECT DISTINCT
        caselou_code,
        caselou_followup_type,
        caselou_followup_date,
        caselou_followup_current_activ,
        caselou_followup_notes,
        caselou_followup_exclusion_non,
        caselou_followup_interim_bill_
    FROM public.caselou_followup_incase
) cfi
JOIN public.lou l
    ON cfi.caselou_code = l.lou_case_code
JOIN public.customers c
    ON l.lou_customer_code = c.customerscode
JOIN (
    SELECT
        benefit_rows.lou_code,
        STRING_AGG(
            DISTINCT benefit_rows.benefit,
            ', '
            ORDER BY benefit_rows.benefit
        ) AS benefit
    FROM (
        SELECT
            lba_inner.lou_benefit_amount_lou_code AS lou_code,
            COALESCE(
                NULLIF(BTRIM(lba_inner.lou_benefit_amount_sbenefit_na), ''),
                NULLIF(BTRIM(lba_inner.lou_benefit_amount_pbenefit_na), '')
            ) AS benefit
        FROM public.lou_benefit_amount lba_inner
        WHERE lba_inner.lou_benefit_amount_total_amoun > 0
    ) benefit_rows
    GROUP BY benefit_rows.lou_code
) lba
    ON l.lou_code = lba.lou_code
LEFT JOIN (
    SELECT
        lou_code,
        STRING_AGG(
            DISTINCT NULLIF(BTRIM(lou_diagnosisname), ''),
            ', '
        ) AS "diagnosisName"
    FROM public.loudiagnosis
    GROUP BY lou_code
) ld
    ON l.lou_code = ld.lou_code
"""

DECLINE_REPORT_QUERY = """
SELECT
    cldl.decline_letter_code AS "referenceNumber",
    c.customernamebytype AS "corporate",
    dl.decline_letter_member_name AS "memberName",
    dl.decline_letter_member_number AS "memberNumber",
    dl.decline_letter_provider_name AS "providerName",
    TO_CHAR(dl.decline_letter_date, 'YYYY-MM-DD') AS "declinedDate",
    dr.decline_reasons_name AS "declineReason",
    dl.decline_letter_notes AS "declineLetterNotes",
    STRING_AGG(
        DISTINCT NULLIF(BTRIM(d.diagnosisname), ''),
        ', '
        ORDER BY NULLIF(BTRIM(d.diagnosisname), '')
    ) AS "diagnosisName"
FROM public.caseloudecline_letter cldl
JOIN public.decline_letter dl
    ON dl.decline_letter_code = cldl.decline_letter_code
JOIN public.customers c
    ON c.customerscode = dl.decline_letter_custcode
JOIN public.decline_reasons dr
    ON dr.decline_reasons_code = dl.decline_letter_dreasons_code
LEFT JOIN public.decline_letter_diagnosis dld
    ON dld.decline_letter_code = cldl.decline_letter_code
LEFT JOIN public.diagnosis d
    ON d.diagnosiscode = dld.decline_letter_diagcode
    AND d.diagnosisgroupcode = dld.decline_letter_groupcode
    AND d.diagnosisblockcode = dld.decline_letter_blockcode
GROUP BY
    cldl.decline_letter_code,
    c.customernamebytype,
    dl.decline_letter_member_name,
    dl.decline_letter_member_number,
    dl.decline_letter_provider_name,
    dl.decline_letter_date,
    dr.decline_reasons_name,
    dl.decline_letter_notes
"""

EXCEL_COLUMNS = [
    ("admissionStatus", "Admission Status"),
    ("customerName", "Customer Name"),
    ("memberName", "Member Name"),
    ("memberNumber", "Member Number"),
    ("referenceNumber", "Reference Number"),
    ("providerName", "Provider Name"),
    ("benefit", "Benefit"),
    ("dateAuthorised", "Date Authorised"),
    ("dischargeDate", "Discharge Date"),
    ("lengthOfStay", "Length Of Stay"),
    ("diagnosisName", "Diagnosis Name"),
    ("louNotes", "LOU Notes"),
    ("reserveAmount", "Reserve Amount"),
    ("discountAmount", "Discount Amount"),
    ("shashifType", "Shashif Type"),
    ("louShashifAmount", "LOU SHASHIF Amount"),
]

FOLLOW_UP_EXCEL_COLUMNS = [
    ("caseLouCode", "Case LOU Code"),
    ("admissionStatus", "Admission Status"),
    ("corporate", "Corporate"),
    ("memberName", "Member Name"),
    ("memberNumber", "Member Number"),
    ("referenceNumber", "Reference Number"),
    ("providerName", "Provider Name"),
    ("benefit", "Benefit"),
    ("dateAuthorised", "Date Authorised"),
    ("dateAdmitted", "Date Admitted"),
    ("amountAuthorised", "Amount Authorised"),
    ("dischargeDate", "Discharge Date"),
    ("lengthOfStay", "Length Of Stay"),
    ("diagnosisName", "Diagnosis Name"),
    ("louNotes", "LOU Notes"),
    ("currentActiveManagement", "Current Active Management"),
    ("notes", "Notes"),
    ("exclusionOrNonPayables", "Exclusion Or Non Payables"),
    ("interimBill", "Interim Bill"),
    ("followUpDate", "Follow Up Date"),
    ("followUpType", "Follow Up Type"),
]

DECLINE_EXCEL_COLUMNS = [
    ("referenceNumber", "Reference Number"),
    ("corporate", "Corporate"),
    ("memberName", "Member Name"),
    ("memberNumber", "Member Number"),
    ("providerName", "Provider Name"),
    ("declinedDate", "Declined Date"),
    ("declineReason", "Decline Reason"),
    ("declineLetterNotes", "Decline Letter Notes"),
    ("diagnosisName", "Diagnosis Name"),
]


def excel_column_name(column_number):
    name = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        name = chr(65 + remainder) + name
    return name


def clean_excel_value(value):
    if value is None:
        return ""
    return "".join(
        char
        for char in str(value)
        if char in "\t\n\r" or ord(char) >= 32
    )


def build_worksheet_xml(items, excel_columns=EXCEL_COLUMNS):
    rows = []
    header_cells = []
    for col_index, column in enumerate(excel_columns, start=1):
        cell_ref = f"{excel_column_name(col_index)}1"
        header_cells.append(
            f'<c r="{cell_ref}" t="inlineStr"><is><t>{escape(column[1])}</t></is></c>'
        )
    rows.append(f'<row r="1">{"".join(header_cells)}</row>')

    for row_index, item in enumerate(items, start=2):
        cells = []
        for col_index, column in enumerate(excel_columns, start=1):
            cell_ref = f"{excel_column_name(col_index)}{row_index}"
            value = escape(clean_excel_value(item.get(column[0])))
            cells.append(
                f'<c r="{cell_ref}" t="inlineStr"><is><t>{value}</t></is></c>'
            )
        rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
    <sheetData>
        {"".join(rows)}
    </sheetData>
</worksheet>'''


def clean_filename_part(value):
    cleaned_value = clean_excel_value(value).strip()
    return "".join("-" if char in '<>:"/\\|?*' else char for char in cleaned_value)


def get_export_date_label(request, date_authorised_start_date=None, date_authorised_end_date=None):
    date_authorised = request.query_params.get("dateAuthorised") or request.query_params.get("DateAuthorised")
    if date_authorised_start_date and date_authorised_end_date:
        return f"{date_authorised_start_date} to {date_authorised_end_date}"
    if date_authorised_start_date:
        return f"From {date_authorised_start_date}"
    if date_authorised_end_date:
        return f"Up to {date_authorised_end_date}"
    if date_authorised:
        return date_authorised
    return datetime.now().strftime("%Y-%m-%d")


def get_follow_up_export_date_label(request, follow_up_start_date=None, follow_up_end_date=None):
    follow_up_date = request.query_params.get("followUpDate") or request.query_params.get("FollowUpDate")
    if follow_up_start_date and follow_up_end_date:
        return f"{follow_up_start_date} to {follow_up_end_date}"
    if follow_up_start_date:
        return f"From {follow_up_start_date}"
    if follow_up_end_date:
        return f"Up to {follow_up_end_date}"
    if follow_up_date:
        return follow_up_date
    return datetime.now().strftime("%Y-%m-%d")


def get_decline_export_date_label(request, declined_start_date=None, declined_end_date=None):
    declined_date = request.query_params.get("declinedDate") or request.query_params.get("DeclinedDate")
    if declined_start_date and declined_end_date:
        return f"{declined_start_date} to {declined_end_date}"
    if declined_start_date:
        return f"From {declined_start_date}"
    if declined_end_date:
        return f"Up to {declined_end_date}"
    if declined_date:
        return declined_date
    return datetime.now().strftime("%Y-%m-%d")


def write_lou_status_report_xlsx(items, date_label):
    export_dir = ensure_care_management_export_dir()
    filename = f"Daily Admission Report - BetterLife - {clean_filename_part(date_label)} - {uuid4().hex[:8]}.xlsx"
    file_path = export_dir / filename

    with ZipFile(file_path, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
    <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>''',
        )
        workbook.writestr(
            "_rels/.rels",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''',
        )
        workbook.writestr(
            "xl/workbook.xml",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <sheets>
        <sheet name="LOU Status Report" sheetId="1" r:id="rId1"/>
    </sheets>
</workbook>''',
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>''',
        )
        workbook.writestr("xl/worksheets/sheet1.xml", build_worksheet_xml(items))

    return filename


def write_follow_up_report_xlsx(items, date_label):
    export_dir = ensure_care_management_export_dir()
    filename = f"Follow Up Report - BetterLife - {clean_filename_part(date_label)} - {uuid4().hex[:8]}.xlsx"
    file_path = export_dir / filename

    with ZipFile(file_path, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
    <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>''',
        )
        workbook.writestr(
            "_rels/.rels",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''',
        )
        workbook.writestr(
            "xl/workbook.xml",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <sheets>
        <sheet name="Follow Up Report" sheetId="1" r:id="rId1"/>
    </sheets>
</workbook>''',
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>''',
        )
        workbook.writestr("xl/worksheets/sheet1.xml", build_worksheet_xml(items, FOLLOW_UP_EXCEL_COLUMNS))

    return filename


def write_decline_report_xlsx(items, date_label):
    export_dir = ensure_care_management_export_dir()
    filename = f"Decline Report - BetterLife - {clean_filename_part(date_label)} - {uuid4().hex[:8]}.xlsx"
    file_path = export_dir / filename

    with ZipFile(file_path, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
    <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>''',
        )
        workbook.writestr(
            "_rels/.rels",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''',
        )
        workbook.writestr(
            "xl/workbook.xml",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <sheets>
        <sheet name="Decline Report" sheetId="1" r:id="rId1"/>
    </sheets>
</workbook>''',
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>''',
        )
        workbook.writestr("xl/worksheets/sheet1.xml", build_worksheet_xml(items, DECLINE_EXCEL_COLUMNS))

    return filename


def first_header_value(value):
    if not value:
        return value
    return value.split(",")[0].strip()


def build_download_url(request, download_path):
    host = first_header_value(
        request.META.get("HTTP_X_FORWARDED_HOST")
        or request.META.get("HTTP_X_ORIGINAL_HOST")
        or request.META.get("HTTP_HOST")
    )
    scheme = first_header_value(request.META.get("HTTP_X_FORWARDED_PROTO"))

    if not host:
        return request.build_absolute_uri(download_path)

    if not scheme:
        scheme = "https" if "ngrok" in host else request.scheme

    return f"{scheme}://{host}{download_path}"


class LouStatusReportDownloadAPIView(APIView):
    def get(self, request, filename):
        if "/" in filename or "\\" in filename or not filename.endswith(".xlsx"):
            raise Http404

        file_path = get_care_management_export_dir() / filename
        if not file_path.exists():
            raise Http404

        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


class LouStatusReportAPIView(APIView):
    filter_fields = {
        "admissionStatus": "l.lou_pre_auth_status_name",
        "customerName": "c.customernamebytype",
        "memberName": "l.lou_customer_member_name",
        "memberNumber": "l.lou_customer_member_numberchar",
        "referenceNumber": "l.lou_reference_number",
        "providerName": "l.lou_provider_name",
        "benefit": "lba.benefit",
        "dateAuthorised": "l.lou_service_date",
        "dischargeDate": "l.lou_discharge_date",
        "lengthOfStay": "l.lou_lengh_of_stay",
        "diagnosisName": "ld.\"diagnosisName\"",
        "louNotes": "l.lou_notes",
        "reserveAmount": "l.lou_total_amount",
        "discountAmount": "l.lou_discount_amount",
        "shashifType": SHASHIF_TYPE_EXPRESSION,
        "louShashifAmount": "l.lou_shashif_amount",
        "AdmissionStatus": "l.lou_pre_auth_status_name",
        "CustomerName": "c.customernamebytype",
        "MemberName": "l.lou_customer_member_name",
        "MemberNumber": "l.lou_customer_member_numberchar",
        "ReferenceNumber": "l.lou_reference_number",
        "ProviderName": "l.lou_provider_name",
        "Benefit": "lba.benefit",
        "DateAuthorised": "l.lou_service_date",
        "DischargeDate": "l.lou_discharge_date",
        "LengthOfStay": "l.lou_lengh_of_stay",
        "DiagnosisName": "ld.\"diagnosisName\"",
        "LouNotes": "l.lou_notes",
        "ReserveAmount": "l.lou_total_amount",
        "DiscountAmount": "l.lou_discount_amount",
        "ShashifType": SHASHIF_TYPE_EXPRESSION,
        "LouSHASHIFAMOUNT": "l.lou_shashif_amount",
    }

    date_filter_fields = {
        "dateAuthorised",
        "dischargeDate",
        "DateAuthorised",
        "DischargeDate",
    }

    def get(self, request):
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("pageSize", 10))
        except ValueError:
            return Response(
                {"error": "page and pageSize must be valid numbers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if page < 1:
            return Response(
                {"error": "page must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if page_size < 1:
            return Response(
                {"error": "pageSize must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        page_size = min(page_size, 500)
        offset = (page - 1) * page_size

        where_clauses = []
        params = []

        for field_name, column_name in self.filter_fields.items():
            value = request.query_params.get(field_name)
            if value:
                if field_name in self.date_filter_fields:
                    where_clauses.append(f"DATE({column_name}) = %s")
                    params.append(value)
                else:
                    where_clauses.append(f"{column_name}::text ILIKE %s")
                    params.append(f"%{value}%")

        date_authorised_start_date = request.query_params.get("dateAuthorisedStartDate") or request.query_params.get("start_date")
        date_authorised_end_date = request.query_params.get("dateAuthorisedEndDate") or request.query_params.get("end_date")
        if date_authorised_start_date and date_authorised_end_date:
            where_clauses.append("DATE(l.lou_service_date) BETWEEN %s AND %s")
            params.extend([date_authorised_start_date, date_authorised_end_date])
        elif date_authorised_start_date:
            where_clauses.append("DATE(l.lou_service_date) >= %s")
            params.append(date_authorised_start_date)
        elif date_authorised_end_date:
            where_clauses.append("DATE(l.lou_service_date) <= %s")
            params.append(date_authorised_end_date)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        count_query = f"""
        SELECT COUNT(*) FROM (
            {LOU_STATUS_REPORT_QUERY}
            {where_sql}
        ) AS lou_status_report_count
        """

        data_query = f"""
        {LOU_STATUS_REPORT_QUERY}
        {where_sql}
        ORDER BY l.lou_service_date DESC NULLS LAST, "referenceNumber"
        LIMIT %s OFFSET %s
        """

        export_query = f"""
        {LOU_STATUS_REPORT_QUERY}
        {where_sql}
        ORDER BY l.lou_service_date DESC NULLS LAST, "referenceNumber"
        """

        try:
            with connections["default_betterlife"].cursor() as cursor:
                if request.query_params.get("exportdoc", "").lower() == "true":
                    cursor.execute(export_query, params)
                    columns = [col[0] for col in cursor.description]
                    items = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    date_label = get_export_date_label(request, date_authorised_start_date, date_authorised_end_date)
                    filename = write_lou_status_report_xlsx(items, date_label)
                    download_path = reverse("lou-status-report-download", kwargs={"filename": filename})
                    download_url = build_download_url(request, download_path)

                    return Response(
                        {
                            "downloadUrl": download_url,
                            "downloadPath": download_path,
                            "fileName": filename,
                            "totalItems": len(items),
                        },
                        status=status.HTTP_200_OK,
                    )

                if request.query_params.get("export", "").lower() == "true":
                    cursor.execute(export_query, params)
                    columns = [col[0] for col in cursor.description]
                    items = [dict(zip(columns, row)) for row in cursor.fetchall()]

                    return Response(
                        {
                            "items": items,
                            "totalItems": len(items),
                        },
                        status=status.HTTP_200_OK,
                    )

                cursor.execute(count_query, params)
                total_items = cursor.fetchone()[0]

                cursor.execute(data_query, params + [page_size, offset])
                columns = [col[0] for col in cursor.description]
                items = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as exc:
            return Response(
                {"error": f"Failed to fetch LOU status report: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "items": items,
                "page": page,
                "pageSize": page_size,
                "totalItems": total_items,
                "totalPages": ceil(total_items / page_size) if total_items else 0,
            },
            status=status.HTTP_200_OK,
        )


class FollowUpReportAPIView(APIView):
    filter_fields = {
        "caseLouCode": "cfi.caselou_code",
        "admissionStatus": "l.lou_pre_auth_status_name",
        "corporate": "c.customernamebytype",
        "memberName": "l.lou_customer_member_name",
        "memberNumber": "l.lou_customer_member_numberchar",
        "referenceNumber": "l.lou_reference_number",
        "providerName": "l.lou_provider_name",
        "benefit": "lba.benefit",
        "dateAuthorised": "l.lou_creation_date",
        "dateAdmitted": "l.lou_service_date",
        "amountAuthorised": "l.lou_total_amount",
        "dischargeDate": "l.lou_discharge_date",
        "lengthOfStay": "l.lou_lengh_of_stay",
        "diagnosisName": "ld.\"diagnosisName\"",
        "louNotes": "l.lou_notes",
        "currentActiveManagement": "cfi.caselou_followup_current_activ",
        "notes": "cfi.caselou_followup_notes",
        "exclusionOrNonPayables": "cfi.caselou_followup_exclusion_non",
        "interimBill": "cfi.caselou_followup_interim_bill_",
        "followUpDate": "cfi.caselou_followup_date",
        "followUpType": FOLLOW_UP_TYPE_EXPRESSION,
        "caselou_code": "cfi.caselou_code",
        "AdmissionStatus": "l.lou_pre_auth_status_name",
        "Corporate": "c.customernamebytype",
        "MemberName": "l.lou_customer_member_name",
        "MemberNumber": "l.lou_customer_member_numberchar",
        "ReferenceNumber": "l.lou_reference_number",
        "ProviderName": "l.lou_provider_name",
        "Benefit": "lba.benefit",
        "DateAuthorised": "l.lou_creation_date",
        "DateAdmitted": "l.lou_service_date",
        "AmountAuthorised": "l.lou_total_amount",
        "DischargeDate": "l.lou_discharge_date",
        "LengthOfStay": "l.lou_lengh_of_stay",
        "DiagnosisName": "ld.\"diagnosisName\"",
        "LouNotes": "l.lou_notes",
        "CurrentActiveManagement": "cfi.caselou_followup_current_activ",
        "Notes": "cfi.caselou_followup_notes",
        "ExclusionOrNonPayables": "cfi.caselou_followup_exclusion_non",
        "InterimBill": "cfi.caselou_followup_interim_bill_",
        "FollowUpDate": "cfi.caselou_followup_date",
        "FollowUpType": FOLLOW_UP_TYPE_EXPRESSION,
    }

    date_filter_fields = {
        "dateAuthorised",
        "dateAdmitted",
        "dischargeDate",
        "followUpDate",
        "DateAuthorised",
        "DateAdmitted",
        "DischargeDate",
        "FollowUpDate",
    }

    def apply_date_range_filter(self, request, where_clauses, params, field_name, column_name):
        start_date = request.query_params.get(f"{field_name}StartDate")
        end_date = request.query_params.get(f"{field_name}EndDate")
        if field_name == "followUpDate":
            start_date = start_date or request.query_params.get("start_date")
            end_date = end_date or request.query_params.get("end_date")

        if start_date and end_date:
            where_clauses.append(f"DATE({column_name}) BETWEEN %s AND %s")
            params.extend([start_date, end_date])
        elif start_date:
            where_clauses.append(f"DATE({column_name}) >= %s")
            params.append(start_date)
        elif end_date:
            where_clauses.append(f"DATE({column_name}) <= %s")
            params.append(end_date)

        return start_date, end_date

    def get(self, request):
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("pageSize", 10))
        except ValueError:
            return Response(
                {"error": "page and pageSize must be valid numbers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if page < 1:
            return Response(
                {"error": "page must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if page_size < 1:
            return Response(
                {"error": "pageSize must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        page_size = min(page_size, 500)
        offset = (page - 1) * page_size

        where_clauses = []
        params = []

        for field_name, column_name in self.filter_fields.items():
            value = request.query_params.get(field_name)
            if value:
                if field_name in self.date_filter_fields:
                    where_clauses.append(f"DATE({column_name}) = %s")
                    params.append(value)
                else:
                    where_clauses.append(f"{column_name}::text ILIKE %s")
                    params.append(f"%{value}%")

        self.apply_date_range_filter(request, where_clauses, params, "dateAuthorised", "l.lou_creation_date")
        self.apply_date_range_filter(request, where_clauses, params, "dateAdmitted", "l.lou_service_date")
        self.apply_date_range_filter(request, where_clauses, params, "dischargeDate", "l.lou_discharge_date")
        follow_up_start_date, follow_up_end_date = self.apply_date_range_filter(request, where_clauses, params, "followUpDate", "cfi.caselou_followup_date")

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        count_query = f"""
        SELECT COUNT(*) FROM (
            {FOLLOW_UP_REPORT_QUERY}
            {where_sql}
        ) AS follow_up_report_count
        """

        data_query = f"""
        {FOLLOW_UP_REPORT_QUERY}
        {where_sql}
        ORDER BY cfi.caselou_followup_date DESC NULLS LAST, "referenceNumber"
        LIMIT %s OFFSET %s
        """

        export_query = f"""
        {FOLLOW_UP_REPORT_QUERY}
        {where_sql}
        ORDER BY cfi.caselou_followup_date DESC NULLS LAST, "referenceNumber"
        """

        try:
            with connections["default_betterlife"].cursor() as cursor:
                if request.query_params.get("exportdoc", "").lower() == "true":
                    cursor.execute(export_query, params)
                    columns = [col[0] for col in cursor.description]
                    items = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    date_label = get_follow_up_export_date_label(request, follow_up_start_date, follow_up_end_date)
                    filename = write_follow_up_report_xlsx(items, date_label)
                    download_path = reverse("lou-status-report-download", kwargs={"filename": filename})
                    download_url = build_download_url(request, download_path)

                    return Response(
                        {
                            "downloadUrl": download_url,
                            "downloadPath": download_path,
                            "fileName": filename,
                            "totalItems": len(items),
                        },
                        status=status.HTTP_200_OK,
                    )

                if request.query_params.get("export", "").lower() == "true":
                    cursor.execute(export_query, params)
                    columns = [col[0] for col in cursor.description]
                    items = [dict(zip(columns, row)) for row in cursor.fetchall()]

                    return Response(
                        {
                            "items": items,
                            "totalItems": len(items),
                        },
                        status=status.HTTP_200_OK,
                    )

                cursor.execute(count_query, params)
                total_items = cursor.fetchone()[0]

                cursor.execute(data_query, params + [page_size, offset])
                columns = [col[0] for col in cursor.description]
                items = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as exc:
            return Response(
                {"error": f"Failed to fetch Follow Up report: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "items": items,
                "page": page,
                "pageSize": page_size,
                "totalItems": total_items,
                "totalPages": ceil(total_items / page_size) if total_items else 0,
            },
            status=status.HTTP_200_OK,
        )


class DeclineReportAPIView(APIView):
    filter_fields = {
        "referenceNumber": "decline_report.\"referenceNumber\"",
        "corporate": "decline_report.\"corporate\"",
        "memberName": "decline_report.\"memberName\"",
        "memberNumber": "decline_report.\"memberNumber\"",
        "providerName": "decline_report.\"providerName\"",
        "declinedDate": "decline_report.\"declinedDate\"",
        "declineReason": "decline_report.\"declineReason\"",
        "declineLetterNotes": "decline_report.\"declineLetterNotes\"",
        "diagnosisName": "decline_report.\"diagnosisName\"",
        "ReferenceNumber": "decline_report.\"referenceNumber\"",
        "Corporate": "decline_report.\"corporate\"",
        "MemberName": "decline_report.\"memberName\"",
        "MemberNumber": "decline_report.\"memberNumber\"",
        "ProviderName": "decline_report.\"providerName\"",
        "DeclinedDate": "decline_report.\"declinedDate\"",
        "DeclineReason": "decline_report.\"declineReason\"",
        "DeclineLetterNotes": "decline_report.\"declineLetterNotes\"",
        "DiagnosisName": "decline_report.\"diagnosisName\"",
    }

    date_filter_fields = {
        "declinedDate",
        "DeclinedDate",
    }

    def apply_date_range_filter(self, request, where_clauses, params, field_name, column_name):
        start_date = request.query_params.get(f"{field_name}StartDate") or request.query_params.get("start_date")
        end_date = request.query_params.get(f"{field_name}EndDate") or request.query_params.get("end_date")

        if start_date and end_date:
            where_clauses.append(f"{column_name} BETWEEN %s AND %s")
            params.extend([start_date, end_date])
        elif start_date:
            where_clauses.append(f"{column_name} >= %s")
            params.append(start_date)
        elif end_date:
            where_clauses.append(f"{column_name} <= %s")
            params.append(end_date)

        return start_date, end_date

    def get(self, request):
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("pageSize", 10))
        except ValueError:
            return Response(
                {"error": "page and pageSize must be valid numbers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if page < 1:
            return Response(
                {"error": "page must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if page_size < 1:
            return Response(
                {"error": "pageSize must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        page_size = min(page_size, 500)
        offset = (page - 1) * page_size

        where_clauses = []
        params = []

        for field_name, column_name in self.filter_fields.items():
            value = request.query_params.get(field_name)
            if value:
                if field_name in self.date_filter_fields:
                    where_clauses.append(f"{column_name} = %s")
                    params.append(value)
                else:
                    where_clauses.append(f"{column_name}::text ILIKE %s")
                    params.append(f"%{value}%")

        declined_start_date, declined_end_date = self.apply_date_range_filter(request, where_clauses, params, "declinedDate", "decline_report.\"declinedDate\"")

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        report_query = f"""
        SELECT * FROM (
            {DECLINE_REPORT_QUERY}
        ) AS decline_report
        {where_sql}
        """

        count_query = f"""
        SELECT COUNT(*) FROM (
            {report_query}
        ) AS decline_report_count
        """

        data_query = f"""
        {report_query}
        ORDER BY decline_report."declinedDate" DESC NULLS LAST, decline_report."referenceNumber"
        LIMIT %s OFFSET %s
        """

        export_query = f"""
        {report_query}
        ORDER BY decline_report."declinedDate" DESC NULLS LAST, decline_report."referenceNumber"
        """

        try:
            with connections["default_betterlife"].cursor() as cursor:
                if request.query_params.get("exportdoc", "").lower() == "true":
                    cursor.execute(export_query, params)
                    columns = [col[0] for col in cursor.description]
                    items = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    date_label = get_decline_export_date_label(request, declined_start_date, declined_end_date)
                    filename = write_decline_report_xlsx(items, date_label)
                    download_path = reverse("lou-status-report-download", kwargs={"filename": filename})
                    download_url = build_download_url(request, download_path)

                    return Response(
                        {
                            "downloadUrl": download_url,
                            "downloadPath": download_path,
                            "fileName": filename,
                            "totalItems": len(items),
                        },
                        status=status.HTTP_200_OK,
                    )

                if request.query_params.get("export", "").lower() == "true":
                    cursor.execute(export_query, params)
                    columns = [col[0] for col in cursor.description]
                    items = [dict(zip(columns, row)) for row in cursor.fetchall()]

                    return Response(
                        {
                            "items": items,
                            "totalItems": len(items),
                        },
                        status=status.HTTP_200_OK,
                    )

                cursor.execute(count_query, params)
                total_items = cursor.fetchone()[0]

                cursor.execute(data_query, params + [page_size, offset])
                columns = [col[0] for col in cursor.description]
                items = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as exc:
            return Response(
                {"error": f"Failed to fetch Decline report: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "items": items,
                "page": page,
                "pageSize": page_size,
                "totalItems": total_items,
                "totalPages": ceil(total_items / page_size) if total_items else 0,
            },
            status=status.HTTP_200_OK,
        )
