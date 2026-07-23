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
    l.lou_pre_auth_status_name AS "admissionStatus",
    c.customernamebytype AS "customerName",
    l.lou_customer_member_name AS "memberName",
    l.lou_customer_member_numberchar AS "memberNumber",
    l.lou_reference_number AS "referenceNumber",
    l.lou_provider_name AS "providerName",
    {BENEFIT_EXPRESSION} AS "benefit",
    TO_CHAR(l.lou_service_date, 'YYYY-MM-DD') AS "dateAuthorised",
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
JOIN public.lou_benefit_amount lba
    ON l.lou_code = lba.lou_benefit_amount_lou_code
   AND lba.lou_benefit_amount_total_amoun > 0
LEFT JOIN (
    SELECT
        lou_code,
        STRING_AGG(
            DISTINCT NULLIF(BTRIM(lou_groupname), ''),
            ', '
        ) AS "diagnosisGroupName",
        STRING_AGG(
            DISTINCT NULLIF(BTRIM(lou_blockname), ''),
            ', '
        ) AS "diagnosisBlockName",
        STRING_AGG(
            DISTINCT NULLIF(BTRIM(lou_diagnosisname), ''),
            ', '
        ) AS "diagnosisName"
    FROM public.loudiagnosis
    GROUP BY lou_code
) ld
    ON l.lou_code = ld.lou_code
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


def build_worksheet_xml(items):
    rows = []
    header_cells = []
    for col_index, column in enumerate(EXCEL_COLUMNS, start=1):
        cell_ref = f"{excel_column_name(col_index)}1"
        header_cells.append(
            f'<c r="{cell_ref}" t="inlineStr"><is><t>{escape(column[1])}</t></is></c>'
        )
    rows.append(f'<row r="1">{"".join(header_cells)}</row>')

    for row_index, item in enumerate(items, start=2):
        cells = []
        for col_index, column in enumerate(EXCEL_COLUMNS, start=1):
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


def write_lou_status_report_xlsx(items):
    export_dir = ensure_care_management_export_dir()
    filename = f"lou_status_report_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}.xlsx"
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
        "benefit": BENEFIT_EXPRESSION,
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
        "Benefit": BENEFIT_EXPRESSION,
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
                if request.query_params.get("export", "").lower() == "true":
                    cursor.execute(export_query, params)
                    columns = [col[0] for col in cursor.description]
                    items = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    filename = write_lou_status_report_xlsx(items)
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
