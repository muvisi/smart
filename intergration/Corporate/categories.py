import requests
import logging
import uuid
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from engine.models import HaisCategorySyncSuccess, HaisCategorySyncFailure

logger = logging.getLogger(__name__)

class SmartCategorySyncService:
    def __init__(self):
        self.mssql_alias = 'external_mssql'
        self.audit_db = 'default'
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates with SMART API."""
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
            logger.error(f"SMART Category Auth Failure: {str(e)}")
            return None

    def run_category_sync(self):
        """Fetches and syncs Benefit Categories from MSSQL to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch TOP 50 from the specific category view
                mssql_cursor.execute("SELECT TOP 50 * FROM dbo.smart_categories_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No categories to sync."}

                sync_stats["total"] = len(rows)
                self.smart_token = self._get_smart_token()
                
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for row in rows:
                    val = dict(zip(columns, row))
                    success = self._process_category(mssql_cursor, val)
                    
                    if success:
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            logger.error(f"Category Sync Database Error: {str(e)}")
            return {"status": "error", "message": "External database connection failed."}

    def _process_category(self, mssql_cursor, val):
        """Handles API call and Atomic Audit logging."""
        cln_cat_code = f"{val.get('category_name')}-{val.get('anniv')}"
        
        smart_payload = {
            'catDesc': cln_cat_code,
            'clnPolCode': val.get('corp_id'),
            'userId': val.get('user_id'),
            'clnCatCode': cln_cat_code,
            'country': "KE",
            'customerid': settings.SMART_CUSTOMER_ID
        }

        # 2. API Call (Outside Transaction Block)
        res_data = {}
        status_code = 500
        try:
            api_url = f"{settings.SMART_API_BASE_URL}benefitCategories?{urlencode(smart_payload)}"
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
            res_data = {"error": "Network/Response Failure", "details": str(e)}

        # 3. Atomic Database Update and Audit
        try:
            with transaction.atomic(using=self.audit_db):
                # Status Mapping: Success = 2, Failure = 4
                sync_status = 2 if is_ok else 4

                # Update corp_groups table (MSSQL)
                update_query = """
                    UPDATE corp_groups 
                    SET sync = %s 
                    WHERE corp_id = %s AND anniv = %s AND category = %s
                """
                mssql_cursor.execute(update_query, [
                    sync_status, 
                    val.get('corp_id'), 
                    val.get('anniv'), 
                    val.get('category_name')
                ])

                # Audit Entry
                audit_fields = {
                    "corp_id": val.get('corp_id'),
                    "category_name": val.get('category_name'),
                    "request_object": smart_payload,
                    "anniv": val.get('anniv'),
                    "user_id": val.get('user_id'),
                    "status_code": status_code,
                    "smart_response": res_data
                }

                if is_ok:
                    HaisCategorySyncSuccess.objects.create(**audit_fields)
                else:
                    HaisCategorySyncFailure.objects.create(**audit_fields)

            return is_ok

        except Exception as e:
            logger.critical(f"Atomic Rollback for Category {cln_cat_code}: {str(e)}")
            return False
        
        
        
import json
import requests
import logging
import urllib3
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from engine.models import HaisCategorySyncSuccess, HaisCategorySyncFailure

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartCategorySyncTask:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.audit_db = 'default'  # PostgreSQL
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates with SMART API using Form-data logic."""
        try:
            auth_payload = {
                "client_id": settings.SMART_CLIENT_ID,
                "client_secret": settings.SMART_CLIENT_SECRET,
                "grant_type": settings.SMART_GRANT_TYPE
            }
            resp = requests.post(
                settings.SMART_ACCESS_TOKEN,
                data=auth_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                verify=False,
                timeout=30
            )
            return resp.json().get("access_token")
        except Exception as e:
            print(f"❌ SMART Auth Error: {e}")
            return None

    def run_sync(self):
        print("\n🏢 CORPORATE CATEGORY SYNC STARTED")
        stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as cursor:
                # Fetching corporate records
                cursor.execute("SELECT TOP 50 * FROM dbo.smart_categories_new")
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

                if not rows:
                    print(">>> SYNC: No pending corporate categories.")
                    return {"status": "skipped", "message": "No records."}

                categories = [dict(zip(columns, row)) for row in rows]
                stats["total"] = len(categories)

                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for category in categories:
                    if self._process_record(cursor, category):
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1

            print(f"✅ DONE → Success: {stats['success']}, Failed: {stats['failed']}\n")
            return {"status": "success", "stats": stats}

        except DatabaseError as e:
            print(f"❌ MSSQL connection failed: {str(e)}")
            return {"status": "error", "message": "DB connection failed."}

    def _process_record(self, mssql_cursor, val):
        """Processes a single Corporate category."""
        
        cln_cat_code = f"{val.get('category_name')}-{val.get('anniv')}"
        
        # 1. Prepare Payload (All to String)
        smart_payload = {
            'catDesc': str(cln_cat_code),
            'clnPolCode': str(val.get('corp_id', "")),
            'userId': str(val.get('user_id', "") or "SYSTEM"),
            'clnCatCode': str(cln_cat_code),
            'country': "KE",
            'customerid': str(settings.SMART_CUSTOMER_ID)
        }

        # 2. Construct URL with Query Params
        encoded_params = urlencode(smart_payload)
        api_url = f"{settings.SMART_API_BASE_URL}benefitCategories?{encoded_params}"

        res_data = {}
        status_code = 500
        is_ok = False
        
        try:
            # 3. API Call
            res = requests.post(
                api_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                verify=False, 
                timeout=25
            )
            status_code = res.status_code
            
            try:
                res_data = res.json()
            except:
                res_data = {"raw_response": res.text}
                
            is_ok = str(res_data.get('successful')).lower() == 'true'
            
            if is_ok:
                print(f"✅ Success: {cln_cat_code}")
            else:
                print(f"❌ Rejected: {cln_cat_code} - {res_data.get('status_msg')}")

        except Exception as e:
            print(f"!!! API Error for {cln_cat_code}: {e}")
            res_data = {"error": "API communication failure", "details": str(e)}

        # 4. Atomic Update & Log (Strictly matching your provided Models)
        try:
            with transaction.atomic(using=self.audit_db):
                sync_status = 2 if is_ok else 4

                # Update MSSQL
                mssql_cursor.execute("""
                    UPDATE dbo.corp_groups 
                    SET sync = %s 
                    WHERE corp_id = %s AND anniv = %s AND category = %s
                """, [
                    sync_status, 
                    val.get('corp_id'), 
                    val.get('anniv'), 
                    val.get('category_name')
                ])

                # Map fields STRICTLY to your HaisCategorySyncSuccess/Failure models
                audit_fields = {
                    "corp_id": str(val.get('corp_id')),
                    "category_name": str(val.get('category_name')),
                    "request_object": smart_payload, # JSONField
                    "anniv": str(val.get('anniv')),
                    "user_id": str(val.get('user_id') or "SYSTEM"),
                    "status_code": int(status_code), # IntegerField
                    "smart_response": res_data # JSONField
                }

                if is_ok:
                    HaisCategorySyncSuccess.objects.create(**audit_fields)
                else:
                    HaisCategorySyncFailure.objects.create(**audit_fields)

            return is_ok
        except Exception as e:
            print(f"❌ PostgreSQL Logging Failure for {cln_cat_code}: {e}")
            return False