import requests
import logging
import uuid
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from engine.models import MemberSyncSuccess, MemberSyncFailure  # Adjust import path

logger = logging.getLogger(__name__)

class SmartCorporateMemberSyncService:
    def __init__(self):
        self.mssql_alias = 'external_mssql'
        self.audit_db = 'default'
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates with SMART API to retrieve the Bearer token."""
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
            logger.error(f"SMART Auth Failure (Corporate Members): {str(e)}")
            return None

    def run_corporate_member_sync(self):
        """Fetches unsynced Corporate members and pushes them to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # Fetch TOP 25 as per business logic
                query = "SELECT TOP 25 * FROM dbo.smart_corp_members_new"
                mssql_cursor.execute(query)
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No corporate members to sync."}

                sync_stats["total"] = len(rows)
                self.smart_token = self._get_smart_token()
                
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for row in rows:
                    val = dict(zip(columns, row))
                    success = self._process_member(mssql_cursor, val)
                    
                    if success:
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            logger.error(f"MSSQL Connection Error: {str(e)}")
            return {"status": "error", "message": "Source database connection failed."}

    def _process_member(self, mssql_cursor, val):
        """Handles Transformation, API Call, and Atomic Update/Audit."""
        # 1. Data Transformation
        names = (val.get('member_name') or "").split()
        surname = names[0] if len(names) > 0 else ""
        second_name = names[1] if len(names) > 1 else ""
        third_name = names[2] if len(names) > 2 else ""

        raw_phone = str(val.get('mobile_no', '')).replace(" ", "")
        mobile_phone = f"254{raw_phone[-9:]}" if raw_phone else ""

        smart_payload = {
            'familyCode': val.get('family_no'),
            'membershipNumber': val.get('member_no'),
            'staffNumber': val.get('member_no'),
            'surname': surname,
            'secondName': second_name,
            'thirdName': third_name,
            'otherNames': "null",
            'idNumber': "",
            'dob': val.get('dob') or "null",
            'gender': val.get('gender') or "",
            'nhifNumber': "",
            'memType': val.get('member_type'),
            'schemeStartDate': val.get('start_date'),
            'schemeEndDate': val.get('end_date'),
            'clnCatCode': f"{val.get('category')}-{val.get('anniv')}",
            'clnPolCode': val.get('corp_id'),
            'phone_number': mobile_phone,
            'email_address': val.get('email', ""),
            'userID': val.get('user_id'),
            'country': "KE",
            'customerid': settings.SMART_CUSTOMER_ID,
            'roamingCountries': "KE"
        }

        # 2. API Call (Outside Transaction)
        res_data = {}
        status_code = 500
        try:
            api_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(smart_payload)}"
            res = requests.post(
                api_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                verify=False, 
                timeout=25
            )
            status_code = res.status_code
            res_data = res.json()
            is_ok = res_data.get('successful') is True
        except Exception as e:
            is_ok = False
            res_data = {"error": str(e)}

        # 3. Atomic Database Block
        try:
            with transaction.atomic(using=self.audit_db):
                sync_status = 1 if is_ok else 2

                # Update HAIS Tables (MSSQL)
                mssql_cursor.execute(
                    "UPDATE member_info SET sync = %s WHERE member_no = %s", 
                    [sync_status, val.get('member_no')]
                )
                mssql_cursor.execute(
                    "UPDATE member_anniversary SET sync = %s WHERE member_no = %s AND anniv = %s",
                    [sync_status, val.get('member_no'), val.get('anniv')]
                )

                # Log to Audit Models (Postgres/Default)
                audit_data = {
                    "member_no": val.get('member_no'),
                    "family_no": val.get('family_no'),
                    "request_object": smart_payload,
                    "surname": surname,
                    "second_name": second_name,
                    "third_name": third_name,
                    "category": val.get('category'),
                    "anniv": val.get('anniv'),
                    "corp_id": val.get('corp_id'),
                    "smart_status": status_code,
                    "smart_response": res_data
                }

                if is_ok:
                    MemberSyncSuccess.objects.create(**audit_data)
                else:
                    MemberSyncFailure.objects.create(**audit_data)

            return is_ok

        except Exception as e:
            logger.critical(f"Atomic Transaction Failure for Member {val.get('member_no')}: {str(e)}")
            return False
import json
import requests
import logging
import urllib3
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from engine.models import MemberSyncSuccess, MemberSyncFailure

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartMemberSyncService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.audit_db = 'default' # PostgreSQL
        self.smart_token = None
        self.session = requests.Session()
        self.session.verify = False 

    def _get_smart_token(self):
        """Authenticates with SMART API using Form-data logic."""
        try:
            auth_payload = {
                "client_id": settings.SMART_CLIENT_ID,
                "client_secret": settings.SMART_CLIENT_SECRET,
                "grant_type": settings.SMART_GRANT_TYPE
            }
            resp = self.session.post(
                settings.SMART_ACCESS_TOKEN,
                data=auth_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )
            return resp.json().get("access_token")
        except Exception as e:
            print(f"❌ SMART Corp Member Auth Error: {e}")
            return None

    def run_member_sync(self):
        """Fetches pending corporate members and syncs via URL Parameters."""
        print("\n🏢 CORPORATE MEMBER SYNC STARTED")
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch TOP 25
                query = "SELECT TOP 25 * FROM dbo.smart_corp_members_new"
                mssql_cursor.execute(query)
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    print(">>> SYNC: No corporate members pending.")
                    return {"status": "success", "message": "No members pending."}

                members = [dict(zip(columns, row)) for row in rows]
                sync_stats["total"] = len(members)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for member in members:
                    if self._process_member(mssql_cursor, member):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            print(f"✅ CORP MEMBER DONE → Success: {sync_stats['success']}, Failed: {sync_stats['failed']}\n")
            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            print(f"❌ Member Sync MSSQL Error: {str(e)}")
            return {"status": "error", "message": "External database unavailable."}

    def _process_member(self, mssql_cursor, val):
        """Handles Name/Phone parsing, URL-based API call, and Atomic Audit."""
        # 1. Data Parsing & Transformation
        member_no = str(val.get('member_no') or "")
        family_no = str(val.get('family_no') or "")
        anniv = str(val.get('anniv') or "")
        cln_cat_code = f"{val.get('category')}-{anniv}"

        # Name splitting
        full_name = (val.get('member_name') or "").strip().split()
        surname = full_name[0] if len(full_name) > 0 else ""
        second_name = full_name[1] if len(full_name) > 1 else ""
        third_name = full_name[2] if len(full_name) > 2 else ""

        # Normalize Phone to 254 Format
        raw_phone = str(val.get('mobile_no', '')).replace(" ", "").replace("+", "")
        mobile_phone = f"254{raw_phone[-9:]}" if len(raw_phone) >= 9 else ""

        # 2. Prepare Payload (All forced to String for urlencode)
        smart_payload = {
            'familyCode': family_no,
            'membershipNumber': member_no,
            'staffNumber': member_no,
            'surname': str(surname),
            'secondName': str(second_name),
            'thirdName': str(third_name),
            'otherNames': "null",
            'idNumber': "",
            'dob': str(val.get('dob') or "null"),
            'gender': str(val.get('gender') or ""),
            'nhifNumber': str(val.get('nhif_no') or ""),
            'memType': str(val.get('member_type') or ""),
            'schemeStartDate': str(val.get('start_date') or ""),
            'schemeEndDate': str(val.get('end_date') or ""),
            'clnCatCode': cln_cat_code,
            'clnPolCode': str(val.get('corp_id', "")),
            'phone_number': mobile_phone,
            'email_address': str(val.get('email', "")),
            'userID': str(val.get('user_id') or "SYSTEM"),
            'country': "KE",
            'customerid': str(settings.SMART_CUSTOMER_ID),
            'roamingCountries': "KE"
        }

        # 3. API Call (URL Parameters logic)
        res_data = {}
        status_code = 500
        is_ok = False
        
        try:
            api_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(smart_payload)}"
            res = self.session.post(
                api_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                timeout=100 
            )
            status_code = res.status_code
            try:
                res_data = res.json()
            except:
                res_data = {"raw_response": res.text}
                
            is_ok = str(res_data.get('successful', '')).lower() == 'true'
            
            if is_ok:
                print(f"✅ Success: Corp Member {member_no} ({surname})")
            else:
                print(f"❌ Rejected: {member_no} - {res_data.get('status_msg')}")

        except Exception as e:
            print(f"!!! API ERROR for Corp Member {member_no}: {e}")
            res_data = {"error": str(e)}

        # 4. Atomic Database Update and Audit Trail
        try:
            with transaction.atomic(using=self.audit_db):
                sync_status = 1 if is_ok else 2

                # Update MSSQL Tables
                mssql_cursor.execute("UPDATE dbo.member_info SET sync = %s WHERE member_no = %s", [sync_status, member_no])
                mssql_cursor.execute("UPDATE dbo.member_anniversary SET sync = %s WHERE member_no = %s AND anniv = %s", [sync_status, member_no, anniv])

                # Log to Audit Models (Postgres)
                audit_data = {
                    "member_no": member_no,
                    "family_no": family_no,
                    "request_object": smart_payload,
                    "surname": surname,
                    "second_name": second_name,
                    "third_name": third_name,
                    "category": str(val.get('category')),
                    "anniv": anniv,
                    "corp_id": str(val.get('corp_id')),
                    "smart_status": int(status_code),
                    "smart_response": res_data
                }

                if is_ok:
                    MemberSyncSuccess.objects.create(**audit_data)
                else:
                    MemberSyncFailure.objects.create(**audit_data)

            return is_ok
        except Exception as e:
            print(f"❌ Atomic Rollback for Corp Member {member_no}: {e}")
            return False