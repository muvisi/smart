import requests
import logging
import uuid
from urllib.parse import urlencode
from django.db import connections, transaction
from django.conf import settings

# Audit Trail Models
from engine.models import MemberSyncSuccess, MemberSyncFailure

logger = logging.getLogger(__name__)

class SmartMemberSyncService:
    def __init__(self):
        self.mssql_alias = 'external_mssql'
        self.smart_token = None

    def _get_smart_token(self):
        params = {
            'client_id': settings.SMART_CLIENT_ID,
            'client_secret': settings.SMART_CLIENT_SECRET,
            'grant_type': settings.SMART_GRANT_TYPE
        }
        try:
            url = f"{settings.SMART_ACCESS_TOKEN}{urlencode(params)}"
            res = requests.post(url, verify=False, timeout=15)
            res.raise_for_status()
            return res.json().get('access_token')
        except Exception as e:
            logger.error(f"SMART Auth Failure: {str(e)}")
            return None

    def run_member_sync(self):
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch TOP 25 pending members
                mssql_cursor.execute("SELECT TOP 25 * FROM dbo.smart_retail_members_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No members pending."}

                sync_stats["total"] = len(rows)
                self.smart_token = self._get_smart_token()
                
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for row_data in [dict(zip(columns, r)) for r in rows]:
                    success = self._sync_single_member(mssql_cursor, row_data)
                    if success: sync_stats["success"] += 1
                    else: sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}
        except Exception as e:
            logger.critical(f"Global Member Sync Failure: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _sync_single_member(self, mssql_cursor, val):
        # --- Variable Extraction ---
        member_no = str(val.get('member_no'))
        family_no = str(val.get('family_no'))
        anniv = str(val.get('anniv'))
        cln_cat_code = f"{family_no}-{anniv}"
        
        # Name splitting logic
        name_parts = (val.get('member_name') or "").split()
        surname = name_parts[0] if len(name_parts) > 0 else ""
        second_name = name_parts[1] if len(name_parts) > 1 else ""
        third_name = name_parts[2] if len(name_parts) > 2 else ""
        other_names = "null"

        # Phone logic (254 + last 9)
        phone_raw = str(val.get('mobile_no', '')).replace(" ", "")
        mobile_phone = f"254{phone_raw[-9:]}" if phone_raw else ""

        # Construct SMART API Payload
        smart_payload = {
            'familyCode': family_no,
            'membershipNumber': member_no,
            'staffNumber': member_no,
            'surname': surname,
            'secondName': second_name,
            'thirdName': third_name,
            'otherNames': other_names,
            'idNumber': "",
            'dob': val.get('dob') if val.get('dob') else "null",
            'gender': val.get('gender') or "",
            'nhifNumber': "",
            'memType': val.get('memType'),
            'schemeStartDate': val.get('start_date'),
            'schemeEndDate': val.get('end_date'),
            'clnCatCode': cln_cat_code,
            'clnPolCode': val.get('scheme_id'),
            'phone_number': mobile_phone,
            'email_address': val.get('email') or "",
            'userID': val.get('user_id'),
            'country': "KE",
            'customerid': settings.SMART_CUSTOMER_ID,
            'roamingCountries': "KE"
        }

        # 1. API Call to SMART
        try:
            api_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(smart_payload)}"
            res = requests.post(api_url, headers={"Authorization": f"Bearer {self.smart_token}"}, verify=False, timeout=25)
            res_data = res.json()
            is_ok = res_data.get('successful') is True
            http_code = res.status_code
        except Exception as e:
            is_ok, http_code, res_data = False, 500, {"error": str(e)}

        # 2. Multi-Table Sync & Audit (Atomic)
        try:
            with transaction.atomic(using='default'):
                # Log outcome to Postgres Audit Trail
                LogModel = MemberSyncSuccess if is_ok else MemberSyncFailure
                LogModel.objects.using('default').create(
                    member_no=member_no,
                    family_no=family_no,
                    request_object=smart_payload,
                    surname=surname,
                    second_name=second_name,
                    third_name=third_name,
                    other_names=other_names,
                    category=cln_cat_code,
                    anniv=anniv,
                    corp_id=val.get('scheme_id'),
                    smart_status=http_code,
                    smart_response=res_data
                )

                # Status Mapping: Success = 1, Failure = 2
                sync_status = 1 if is_ok else 2

                # Update 1: member_info (Primary table)
                mssql_cursor.execute(
                    "UPDATE member_info SET sync = %s WHERE member_no = %s",
                    [sync_status, member_no]
                )

                # Update 2: member_anniversary (History table)
                mssql_cursor.execute(
                    "UPDATE member_anniversary SET sync = %s WHERE member_no = %s AND anniv = %s",
                    [sync_status, member_no, anniv]
                )

                # Update 3: principal_applicant (Principal tracking table)
                # PHP Logic: UPDATE principal_applicant SET sync = :status WHERE family_no = :family_no
                mssql_cursor.execute(
                    "UPDATE principal_applicant SET sync = %s WHERE family_no = %s",
                    [sync_status, family_no]
                )

            return is_ok
        except Exception as e:
            logger.error(f"Database synchronization failed for {member_no}: {str(e)}")
            return False
        
        
        
import json
import requests
import logging
from urllib.parse import urlencode
from django.db import connections, transaction
from django.conf import settings
from engine.models import MemberSyncSuccess, MemberSyncFailure

logger = logging.getLogger(__name__)

class SmartRetailMemberSyncService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.smart_token = None
        self.session = requests.Session()
        self.session.verify = False 

    def _get_smart_token(self):
        """Authenticates with SMART API (15s timeout)."""
        params = {
            'client_id': settings.SMART_CLIENT_ID,
            'client_secret': settings.SMART_CLIENT_SECRET,
            'grant_type': settings.SMART_GRANT_TYPE
        }
        try:
            url = f"{settings.SMART_ACCESS_TOKEN}{urlencode(params)}"
            res = self.session.post(url, timeout=15)
            res.raise_for_status()
            return res.json().get('access_token')
        except Exception as e:
            logger.error(f"SMART Auth Failure: {str(e)}")
            return None

    def run_retail_member_sync(self):
        """Fetches pending members from MSSQL and Syncs to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch TOP 25 Data as JSON-ready dicts
                mssql_cursor.execute("SELECT TOP 25 * FROM dbo.smart_retail_members_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No members pending sync."}

                members_json = [dict(zip(columns, r)) for r in rows]
                sync_stats["total"] = len(members_json)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                # 2. Process Sync Loop
                for member_data in members_json:
                    if self._sync_single_retail_member(mssql_cursor, member_data):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}
        except Exception as e:
            logger.critical(f"Global Retail Member Sync Failure: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _sync_single_retail_member(self, mssql_cursor, val):
        # Extract and Format Variables
        member_no = str(val.get('member_no'))
        family_no = str(val.get('family_no'))
        anniv = str(val.get('anniv'))
        cln_cat_code = f"{family_no}-{anniv}"
        
        # Name splitting
        name_parts = (val.get('member_name') or "").split()
        surname = name_parts[0] if len(name_parts) > 0 else ""
        second_name = name_parts[1] if len(name_parts) > 1 else ""
        third_name = name_parts[2] if len(name_parts) > 2 else ""

        # Phone formatting (KE Standard)
        phone_raw = str(val.get('mobile_no', '')).replace(" ", "")
        mobile_phone = f"254{phone_raw[-9:]}" if phone_raw else ""

        # Payload Construction
        smart_payload = {
            'familyCode': family_no,
            'membershipNumber': member_no,
            'staffNumber': member_no,
            'surname': surname,
            'secondName': second_name,
            'thirdName': third_name,
            'otherNames': "null",
            'idNumber': "",
            'dob': val.get('dob') if val.get('dob') else "null",
            'gender': val.get('gender') or "",
            'nhifNumber': "",
            'memType': val.get('memType'),
            'schemeStartDate': val.get('start_date'),
            'schemeEndDate': val.get('end_date'),
            'clnCatCode': cln_cat_code,
            'clnPolCode': val.get('scheme_id'),
            'phone_number': mobile_phone,
            'email_address': val.get('email') or "",
            'userID': val.get('user_id'),
            'country': "KE",
            'customerid': settings.SMART_CUSTOMER_ID,
            'roamingCountries': "KE"
        }

        # 1. API Post (100s Timeout)
        try:
            api_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(smart_payload)}"
            res = self.session.post(
                api_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                timeout=100
            )
            res_data = res.json()
            is_ok = res_data.get('successful') is True
            http_code = res.status_code
        except Exception as e:
            is_ok, http_code, res_data = False, 500, {"error": str(e)}

        # 2. Atomic Coordination (Postgres Audit + MSSQL Updates)
        try:
            with transaction.atomic(using='default'):
                # Log to Postgres
                LogModel = MemberSyncSuccess if is_ok else MemberSyncFailure
                LogModel.objects.create(
                    member_no=member_no,
                    family_no=family_no,
                    request_object=smart_payload,
                    surname=surname,
                    second_name=second_name,
                    third_name=third_name,
                    other_names="null",
                    category=cln_cat_code,
                    anniv=anniv,
                    corp_id=val.get('scheme_id'),
                    smart_status=http_code,
                    smart_response=res_data
                )

                # Retail Status Mapping (1: Success, 2: Failure)
                sync_status = 1 if is_ok else 2

                # Update MSSQL member_info
                mssql_cursor.execute(
                    "UPDATE member_info SET sync = %s WHERE member_no = %s",
                    [sync_status, member_no]
                )

                # Update MSSQL member_anniversary
                mssql_cursor.execute(
                    "UPDATE member_anniversary SET sync = %s WHERE member_no = %s AND anniv = %s",
                    [sync_status, member_no, anniv]
                )

                # Update MSSQL principal_applicant
                mssql_cursor.execute(
                    "UPDATE principal_applicant SET sync = %s WHERE family_no = %s",
                    [sync_status, family_no]
                )

            return is_ok
        except Exception as e:
            logger.error(f"Atomic Rollback for Member {member_no}: {str(e)}")
            return False