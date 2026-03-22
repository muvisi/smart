import requests
import logging
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings

from engine.models import WaitingPeriodSyncFailure, WaitingPeriodSyncSuccess

logger = logging.getLogger(__name__)

class SmartRetailWaitingPeriodSyncService:
    def __init__(self):
        self.mssql_alias = 'external_mssql'
        self.default_db = 'default' # Typically your Postgres/Audit DB
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates with SMART API with timeout and error handling."""
        params = {
            'client_id': settings.SMART_CLIENT_ID,
            'client_secret': settings.SMART_CLIENT_SECRET,
            'grant_type': settings.SMART_GRANT_TYPE
        }
        try:
            url = f"{settings.SMART_ACCESS_TOKEN}{urlencode(params)}"
            res = requests.post(url, verify=False, timeout=10)
            res.raise_for_status()
            return res.json().get('access_token')
        except requests.exceptions.RequestException as e:
            logger.error(f"SMART Auth Failure: {str(e)}")
            return None

    def run_retail_waiting_period_sync(self):
        """Main entry point for the sync process."""
        self.smart_token = self._get_smart_token()
        if not self.smart_token:
            return {"status": "error", "message": "Failed to authenticate with SMART."}

        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # Use the new retail view
                query = "SELECT TOP 50 * FROM dbo.smart_retail_waiting_periods_new"
                mssql_cursor.execute(query)
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No records to sync."}

                sync_stats["total"] = len(rows)

                for row in rows:
                    val = dict(zip(columns, row))
                    success = self._process_single_record(mssql_cursor, val)
                    
                    if success:
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            logger.error(f"Source Database Connection Error: {str(e)}")
            return {"status": "error", "message": "Database connection failed."}

    def _process_single_record(self, mssql_cursor, raw_val):
        """
        Handles the API call and the atomic database updates.
        """
        # 1. Prepare Payload
        payload = {
            "is_autogrowth": 0,
            "integ_ben_code": raw_val.get('benefit'),
            "integ_cat_code": raw_val.get('category'),
            "integ_scheme_code": int(raw_val.get('scheme_id', 0)),
            "is_autogrowth2": 0,
            "is_waitingperiod": 1,
            "waiting_days": int(raw_val.get('waiting_period', 0))
        }

        api_params = {'country': "KE", 'customerid': settings.SMART_CUSTOMER_ID}
        api_url = f"{settings.SMART_API_BASE_URL}benefit/rules?{urlencode(api_params)}"

        # 2. API Call (OUTSIDE atomic transaction)
        try:
            response = requests.post(
                api_url, 
                json=payload, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                verify=False, 
                timeout=20
            )
            res_data = response.json()
            status_code = response.status_code
            is_ok = res_data.get('successful') is True
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.warning(f"API Network Failure for {raw_val.get('family_no')}: {str(e)}")
            is_ok = False
            status_code = 500
            res_data = {"error": "Network/JSON Parse Failure", "details": str(e)}

        # 3. Atomic Database Block (INSIDE)
        try:
            # Wrap both DB operations in an atomic block for the Audit DB
            with transaction.atomic(using=self.default_db):
                sync_status = 1 if is_ok else 2

                # Update MSSQL (HAIS)
                update_sql = """
                    UPDATE member_benefits SET wp_sync = %s 
                    WHERE member_no = %s AND anniv = %s AND benefit = %s
                """
                mssql_cursor.execute(update_sql, [
                    sync_status, 
                    raw_val.get('family_no'), 
                    raw_val.get('anniv'),
                    raw_val.get('benefit')
                ])

                # Create Audit Entry in Postgres
                if is_ok:
                    WaitingPeriodSyncSuccess.objects.create(
                        scheme_id=raw_val.get('scheme_id'),
                        family_no=raw_val.get('family_no'),
                        benefit=raw_val.get('benefit'),
                        anniv=raw_val.get('anniv'),
                        request_object=payload,
                        status_code=status_code,
                        smart_response=res_data
                    )
                else:
                    WaitingPeriodSyncFailure.objects.create(
                        scheme_id=raw_val.get('scheme_id'),
                        family_no=raw_val.get('family_no'),
                        category=raw_val.get('category', 'N/A'),
                        benefit=raw_val.get('benefit'),
                        anniv=raw_val.get('anniv'),
                        request_object=payload,
                        status_code=status_code,
                        smart_response=res_data
                    )
            return is_ok

        except Exception as e:
            # If the DB update or Audit Logging fails, we log it and move to next record
            # The transaction.atomic() handles the rollback automatically
            logger.critical(f"Database Integrity Failure for {raw_val.get('family_no')}: {str(e)}")
            return False
        
import json
import requests
import urllib3
import logging
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from engine.models import WaitingPeriodSyncFailure, WaitingPeriodSyncSuccess

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartRetailWaitingPeriodSyncService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.audit_db = 'default' # Postgres
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
            print(f"❌ SMART Waiting Period Auth Error: {e}")
            return None

    def run_retail_waiting_period_sync(self):
        """Main execution loop for retail waiting periods."""
        print("\n⏳ RETAIL WAITING PERIOD SYNC STARTED")
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch TOP 50
                mssql_cursor.execute("SELECT TOP 50 * FROM dbo.smart_retail_waiting_periods_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    print(">>> SYNC: No waiting periods pending.")
                    return {"status": "success", "message": "No records pending."}

                records = [dict(zip(columns, row)) for row in rows]
                sync_stats["total"] = len(records)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                # 2. Process Loop
                for wp_data in records:
                    if self._process_single_record(mssql_cursor, wp_data):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            print(f"✅ WP DONE → Success: {sync_stats['success']}, Failed: {sync_stats['failed']}\n")
            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            print(f"❌ MSSQL Connection Error (Waiting Periods): {str(e)}")
            return {"status": "error", "message": str(e)}

    def _process_single_record(self, mssql_cursor, val):
        family_no = val.get('family_no')
        benefit_id = val.get('benefit')
        
        # 1. Prepare Payload (Ensuring integer logic is preserved for the endpoint)
        smart_payload = {
            "is_autogrowth": 0,
            "integ_ben_code": str(benefit_id),
            "integ_cat_code": str(val.get('category')),
            "integ_scheme_code": str(val.get('scheme_id', '0')),
            "is_autogrowth2": 0,
            "is_waitingperiod": 1,
            "waiting_days": str(val.get('waiting_period', '0'))
        }

        # 2. API Call (100s Timeout)
        res_data = {}
        status_code = 500
        is_ok = False
        
        try:
            api_params = {'country': "KE", 'customerid': settings.SMART_CUSTOMER_ID}
            api_url = f"{settings.SMART_API_BASE_URL}benefit/rules?{urlencode(api_params)}"
            
            response = self.session.post(
                api_url, 
                json=smart_payload, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                timeout=100
            )
            status_code = response.status_code
            try:
                res_data = response.json()
            except:
                res_data = {"raw_response": response.text}
                
            is_ok = str(res_data.get('successful', '')).lower() == 'true'
            
            if is_ok:
                print(f"✅ Success: WP for {family_no} - Benefit {benefit_id}")
            else:
                print(f"❌ Rejected: {family_no} - {res_data.get('status_msg')}")

        except Exception as e:
            print(f"!!! API Error for WP {family_no}: {e}")
            res_data = {"error": str(e)}

        # 3. Atomic Updates & Audit Logging
        try:
            with transaction.atomic(using=self.audit_db):
                # Status: 1 = Success, 2 = Failure
                sync_status = 1 if is_ok else 2

                # Update MSSQL member_benefits (wp_sync field)
                mssql_cursor.execute(
                    """
                    UPDATE dbo.member_benefits SET wp_sync = %s 
                    WHERE member_no = %s AND anniv = %s AND benefit = %s
                    """, 
                    [sync_status, family_no, val.get('anniv'), benefit_id]
                )

                # Log to Postgres Audit Trail
                LogModel = WaitingPeriodSyncSuccess if is_ok else WaitingPeriodSyncFailure
                LogModel.objects.create(
                    scheme_id=str(val.get('scheme_id')),
                    family_no=str(family_no),
                    benefit=str(benefit_id),
                    category=str(val.get('category', 'N/A')),
                    anniv=str(val.get('anniv')),
                    request_object=smart_payload,
                    status_code=int(status_code),
                    smart_response=res_data
                )

            return is_ok
        except Exception as e:
            print(f"❌ Atomic Rollback for WP {family_no}: {e}")
            return False