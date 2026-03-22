import requests
import logging
from urllib.parse import urlencode
from django.db import connections, transaction
from django.conf import settings

from engine.models import HaisCategorySyncFailure, HaisCategorySyncSuccess

logger = logging.getLogger(__name__)

class SmartSyncService:
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

    def run_sync(self):
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        try:
            with connections[self.mssql_alias].cursor() as cursor:
                cursor.execute("SELECT * FROM dbo.smart_retail_categories_new")
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No categories pending."}

                sync_stats["total"] = len(rows)
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "Auth failed."}

                for row_data in [dict(zip(columns, r)) for r in rows]:
                    success = self._sync_single_category(cursor, row_data)
                    if success: sync_stats["success"] += 1
                    else: sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}
        except Exception as e:
            logger.critical(f"Global Sync Failure: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _sync_single_category(self, mssql_cursor, row):
        # Extract variables
        family_no = row.get('category_id') # Used as family_no/corp_id
        anniv = str(row.get('anniv'))
        cat_name = row.get('category_name')
        user_id = str(row.get('user_id'))
        s_type = str(row.get('scheme_type', 'RETAIL')).upper()
        
        display_label = f"{cat_name}-{anniv}"
        payload = {
            'catDesc': display_label,
            'clnPolCode': row.get('scheme_id'),
            'userId': user_id,
            'clnCatCode': display_label,
            'country': "KE",
            'customerid': settings.SMART_CUSTOMER_ID
        }

        # 1. API Post
        try:
            api_url = f"{settings.SMART_API_BASE_URL}benefitCategories?{urlencode(payload)}"
            res = requests.post(api_url, headers={"Authorization": f"Bearer {self.smart_token}"}, verify=False, timeout=25)
            res_data = res.json()
            is_ok = res_data.get('successful') is True
            http_code = res.status_code
        except Exception as e:
            is_ok, http_code, res_data = False, 500, {"error": str(e)}

        # 2. KEEN ATOMIC COORDINATION
        try:
            with transaction.atomic(using='default'):
                # Log to Postgres
                LogModel = HaisCategorySyncSuccess if is_ok else HaisCategorySyncFailure
                LogModel.objects.using('default').create(
                    corp_id=family_no,
                    category_name=cat_name,
                    anniv=anniv,
                    user_id=user_id,
                    request_object=payload,
                    status_code=http_code,
                    smart_response=res_data
                )

                # Update External MSSQL
                if s_type == 'RETAIL':
                    sync_status = 2 if is_ok else 4
                    # PHP Logic: UPDATE member_benefits SET sync = :status WHERE anniv = :anniv AND member_no LIKE :family_no
                    family_no_like = f"%{family_no}%"
                    mssql_cursor.execute(
                        "UPDATE member_benefits SET sync = %s WHERE anniv = %s AND member_no LIKE %s",
                        [sync_status, anniv, family_no_like]
                    )

                    # PHP Logic: $principalStatus = ($this->sync_status == 2 ? 1 : 2)
                    principal_status = 1 if sync_status == 2 else 2
                    # PHP Logic: UPDATE principal_applicant SET sync = :status WHERE family_no = :family_no
                    mssql_cursor.execute(
                        "UPDATE principal_applicant SET sync = %s WHERE family_no = %s",
                        [principal_status, family_no]
                    )
                else:
                    pass
                    # Corporate Path
                    # mssql_status = 1 if is_ok else 2
                    # mssql_cursor.execute(
                    #     "UPDATE dbo.corp_categories SET sync = %s WHERE corp_id = %s AND anniv = %s AND category = %s",
                    #     [mssql_status, row.get('scheme_id'), anniv, cat_name]
                    # )
            return is_ok
        except Exception as e:
            logger.error(f"Atomic Rollback for {family_no}: {str(e)}")
            return False
import json
import requests
import logging
import urllib3
from urllib.parse import urlencode
from django.db import connections, transaction
from django.conf import settings
from engine.models import HaisCategorySyncSuccess, HaisCategorySyncFailure

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartRetailCategorySyncService:
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
            print(f"❌ SMART Retail Auth Error: {e}")
            return None

    def run_retail_category_sync(self):
        """Fetches from smart_retail_categories_new and Syncs via URL Parameters."""
        print("\n🛍️ RETAIL CATEGORY SYNC STARTED")
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as cursor:
                # 1. Fetch Data
                cursor.execute("SELECT * FROM dbo.smart_retail_categories_new")
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

                if not rows:
                    print(">>> SYNC: No retail categories pending.")
                    return {"status": "success", "message": "No records."}

                categories = [dict(zip(columns, r)) for r in rows]
                sync_stats["total"] = len(categories)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                # 2. Process Sync
                for row_data in categories:
                    if self._sync_single_retail_category(cursor, row_data):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            print(f"✅ RETAIL DONE → Success: {sync_stats['success']}, Failed: {sync_stats['failed']}\n")
            return {"status": "success", "stats": sync_stats}
            
        except Exception as e:
            print(f"!!! Global Retail Sync Failure: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _sync_single_retail_category(self, mssql_cursor, row):
        # Mapping fields based on your Retail View
        family_no = str(row.get('category_id') or "") 
        anniv = str(row.get('anniv') or "")
        cat_name = str(row.get('category_name') or "")
        user_id = str(row.get('user_id') or "SYSTEM")
        display_label = f"{cat_name}-{anniv}"
        
        # SMART Payload (Forced to Strings)
        payload = {
            'catDesc': display_label,
            'clnPolCode': str(row.get('scheme_id', "")),
            'userId': user_id,
            'clnCatCode': display_label,
            'country': "KE",
            'customerid': str(settings.SMART_CUSTOMER_ID)
        }

        # 1. API Post (URL Parameters Logic)
        res_data = {}
        http_code = 500
        is_ok = False
        
        try:
            api_url = f"{settings.SMART_API_BASE_URL}benefitCategories?{urlencode(payload)}"
            res = requests.post(
                api_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                verify=False,
                timeout=60
            )
            http_code = res.status_code
            
            try:
                res_data = res.json()
            except:
                res_data = {"raw_response": res.text}
                
            is_ok = str(res_data.get('successful')).lower() == 'true'
            
            if is_ok:
                print(f"✅ Success: {display_label} (Family: {family_no})")
            else:
                print(f"❌ Rejected: {display_label} - {res_data.get('status_msg')}")

        except Exception as e:
            print(f"!!! API Error for {display_label}: {e}")
            res_data = {"error": str(e)}

        # 2. Atomic Database Coordination
        try:
            with transaction.atomic(using=self.audit_db):
                # Map fields to HaisCategorySync Models (Strictly Corporate Schema)
                LogModel = HaisCategorySyncSuccess if is_ok else HaisCategorySyncFailure
                LogModel.objects.create(
                    corp_id=family_no, # Mapping Family No to corp_id field in model
                    category_name=cat_name,
                    anniv=anniv,
                    user_id=user_id,
                    request_object=payload,
                    status_code=int(http_code),
                    smart_response=res_data
                )

                # Retail-Specific MSSQL Updates
                sync_status = 2 if is_ok else 4
                principal_status = 1 if is_ok else 2
                
                # Update Member Benefits
                mssql_cursor.execute(
                    "UPDATE dbo.member_benefits SET sync = %s WHERE anniv = %s AND member_no LIKE %s",
                    [sync_status, anniv, f"%{family_no}%"]
                )

                # Update Principal Applicant
                mssql_cursor.execute(
                    "UPDATE dbo.principal_applicant SET sync = %s WHERE family_no = %s",
                    [principal_status, family_no]
                )

            return is_ok
        except Exception as e:
            print(f"❌ DB Rollback for Retail Category {family_no}: {str(e)}")
            return False