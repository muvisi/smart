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
from urllib.parse import urlencode
from django.db import connections, transaction
from django.conf import settings
from engine.models import HaisCategorySyncSuccess, HaisCategorySyncFailure

logger = logging.getLogger(__name__)

class SmartRetailCategorySyncService:
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

    def run_retail_category_sync(self):
        """Fetches from smart_retail_categories_new and Syncs to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        try:
            with connections[self.mssql_alias].cursor() as cursor:
                # 1. Fetch Data as JSON-ready dicts
                cursor.execute("SELECT * FROM dbo.smart_retail_categories_new")
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No retail categories pending."}

                categories_json = [dict(zip(columns, r)) for r in rows]
                sync_stats["total"] = len(categories_json)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                # 2. Process Sync
                for row_data in categories_json:
                    if self._sync_single_retail_category(cursor, row_data):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}
        except Exception as e:
            logger.critical(f"Global Retail Category Sync Failure: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _sync_single_retail_category(self, mssql_cursor, row):
        family_no = row.get('category_id') 
        anniv = str(row.get('anniv'))
        cat_name = row.get('category_name')
        user_id = str(row.get('user_id', 'SYSTEM'))
        display_label = f"{cat_name}-{anniv}"
        
        # SMART Payload
        payload = {
            'catDesc': display_label,
            'clnPolCode': row.get('scheme_id'),
            'userId': user_id,
            'clnCatCode': display_label,
            'country': "KE",
            'customerid': settings.SMART_CUSTOMER_ID
        }

        # 1. API Post (100s Timeout)
        try:
            api_url = f"{settings.SMART_API_BASE_URL}benefitCategories?{urlencode(payload)}"
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

        # 2. Atomic Database Coordination
        try:
            with transaction.atomic(using='default'):
                # Log to PostgreSQL
                LogModel = HaisCategorySyncSuccess if is_ok else HaisCategorySyncFailure
                LogModel.objects.create(
                    corp_id=family_no,
                    category_name=cat_name,
                    anniv=anniv,
                    user_id=user_id,
                    request_object=payload,
                    status_code=http_code,
                    smart_response=res_data
                )

                # Retail-Specific MSSQL Updates
                # sync = 2 (Success), 4 (Failed)
                sync_status = 2 if is_ok else 4
                
                # Update Member Benefits
                mssql_cursor.execute(
                    "UPDATE member_benefits SET sync = %s WHERE anniv = %s AND member_no LIKE %s",
                    [sync_status, anniv, f"%{family_no}%"]
                )

                # Update Principal Applicant
                # principal sync = 1 (Success), 2 (Failed)
                principal_status = 1 if sync_status == 2 else 2
                mssql_cursor.execute(
                    "UPDATE principal_applicant SET sync = %s WHERE family_no = %s",
                    [principal_status, family_no]
                )

            return is_ok
        except Exception as e:
            logger.error(f"Atomic Rollback for Retail Category {family_no}: {str(e)}")
            return False