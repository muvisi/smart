import json
import uuid
import requests
import logging
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings

from engine.models import ProviderRestrictionSyncFailure, ProviderRestrictionSyncSuccess
# from intergration.models import ProviderRestrictionSyncSuccess, ProviderRestrictionSyncFailure

logger = logging.getLogger(__name__)

class SmartProviderRestrictionSyncService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.audit_db = 'default' 
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates with SMART API (15s timeout)."""
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
            logger.error(f"SMART Restriction Auth Failure: {str(e)}")
            return None

    def run_restriction_sync(self):
        """Fetches from smart_provider_restrictions_new and pushes to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # Source: Provided View
                mssql_cursor.execute("SELECT * FROM dbo.smart_provider_restrictions_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No restrictions to sync."}

                restrictions = [dict(zip(columns, row)) for row in rows]
                sync_stats["total"] = len(restrictions)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for item in restrictions:
                    if self._process_restriction(mssql_cursor, item):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            logger.error(f"Restriction Sync Database Error: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _process_restriction(self, mssql_cursor, val):
        """Processes single record with 120s timeout and audit logging."""
        
        # 1. Payload Mapping (Array format required by SMART)
        smart_payload = [{
            "integSchemeCode": str(val.get('corp_id')),
            "integProvCode": str(val.get('provider_code')),
            "integCatCodes": str(val.get('smart_restriction_category')),
            "lineUser": str(val.get('user_id', '')),
            "countryCode": "KE"
        }]

        # 2. API Call (Using 120s timeout for stability)
        res_data = {}
        status_code = 500
        is_ok = False
        try:
            params = {'country': "KE", 'customerid': settings.SMART_CUSTOMER_ID}
            api_url = f"{settings.SMART_API_BASE_URL}restrictions?{urlencode(params)}"
            
            res = requests.post(
                api_url, 
                json=smart_payload, 
                headers={
                    "Authorization": f"Bearer {self.smart_token}",
                    "customerid": settings.SMART_CUSTOMER_ID,
                    "country": "KE",
                    "Content-Type": "application/json"
                }, 
                verify=False, 
                timeout=120 
            )
            status_code = res.status_code
            res_data = res.json()
            is_ok = str(res_data.get('successful')).lower() == 'true'
        except requests.exceptions.Timeout:
            res_data = {"error": "Timeout", "details": "SMART API did not respond in 120s"}
        except Exception as e:
            res_data = {"error": "Connection Error", "details": str(e)}

        # 3. Atomic Update & Audit Logs (PostgreSQL)
        try:
            with transaction.atomic(using=self.audit_db):
                sync_status = 1 if is_ok else 2

                # Update MSSQL Table: corp_service_points
                mssql_cursor.execute(
                    "UPDATE corp_service_points SET sync = %s WHERE idx = %s",
                    [sync_status, val.get('idx')]
                )

                # Map Common Fields to your Models
                audit_data = {
                    "corp_id": str(val.get('corp_id')),
                    "provider_code": str(val.get('provider_code')),
                    "user_id": str(val.get('user_id', '')),
                    "request_object": smart_payload,
                    "status_code": status_code,
                    "smart_response": res_data
                }

                if is_ok:
                    # Success model uses CharField for category
                    ProviderRestrictionSyncSuccess.objects.create(
                        **audit_data,
                        smart_restriction_category=str(val.get('smart_restriction_category'))
                    )
                else:
                    # Failure model uses JSONField for category
                    # Converting to list if it's a comma-separated string to ensure JSON safety
                    cat_raw = val.get('smart_restriction_category')
                    cat_json = cat_raw.split(',') if isinstance(cat_raw, str) else cat_raw
                    
                    ProviderRestrictionSyncFailure.objects.create(
                        **audit_data,
                        smart_restriction_category=cat_json
                    )

            return is_ok
        except Exception as e:
            logger.critical(f"Integrity Error for Restriction ID {val.get('idx')}: {str(e)}")
            return False