import json
import requests
import logging
import urllib3
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from engine.models import ProviderRestrictionSyncFailure, ProviderRestrictionSyncSuccess

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartProviderRestrictionSyncService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.audit_db = 'default' 
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
            print(f"❌ SMART Restriction Auth Error: {e}")
            return None

    def run_restriction_sync(self):
        """Fetches from smart_provider_restrictions_new and pushes to SMART."""
        print("\n🚫 PROVIDER RESTRICTION SYNC STARTED")
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # Source View
                mssql_cursor.execute("SELECT * FROM dbo.smart_provider_restrictions_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    print(">>> SYNC: No restrictions pending.")
                    return {"status": "success", "message": "No records."}

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

            print(f"✅ RESTRICTION DONE → Success: {sync_stats['success']}, Failed: {sync_stats['failed']}\n")
            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            print(f"❌ Restriction Sync MSSQL Error: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _process_restriction(self, mssql_cursor, val):
        """Processes single record with 120s timeout and audit logging."""
        idx = val.get('idx')
        cat_raw = str(val.get('smart_restriction_category', ''))
        
        # 1. Payload Mapping (SMART expects an Array of Objects)
        smart_payload = [{
            "integSchemeCode": str(val.get('corp_id', '')),
            "integProvCode": str(val.get('provider_code', '')),
            "integCatCodes": cat_raw,
            "lineUser": str(val.get('user_id', '') or "SYSTEM"),
            "countryCode": "KE"
        }]

        # 2. API Call 
        res_data = {}
        status_code = 500
        is_ok = False
        
        try:
            # Query params required for some restriction endpoints
            params = {'country': "KE", 'customerid': settings.SMART_CUSTOMER_ID}
            api_url = f"{settings.SMART_API_BASE_URL}restrictions?{urlencode(params)}"
            
            res = self.session.post(
                api_url, 
                json=smart_payload, 
                headers={
                    "Authorization": f"Bearer {self.smart_token}",
                    "customerid": str(settings.SMART_CUSTOMER_ID),
                    "country": "KE",
                    "Content-Type": "application/json"
                }, 
                timeout=120 
            )
            status_code = res.status_code
            try:
                res_data = res.json()
            except:
                res_data = {"raw_response": res.text}
                
            is_ok = str(res_data.get('successful', '')).lower() == 'true'
            
            if is_ok:
                print(f"✅ Success: Restriction for Corp {val.get('corp_id')} - Provider {val.get('provider_code')}")
            else:
                print(f"❌ Rejected: ID {idx} - {res_data.get('status_msg')}")

        except Exception as e:
            print(f"!!! API ERROR for Restriction ID {idx}: {e}")
            res_data = {"error": str(e)}

        # 3. Atomic Update & Audit Logs
        try:
            with transaction.atomic(using=self.audit_db):
                sync_status = 1 if is_ok else 2

                # Update MSSQL Table: corp_service_points
                mssql_cursor.execute(
                    "UPDATE dbo.corp_service_points SET sync = %s WHERE idx = %s",
                    [sync_status, idx]
                )

                # Base Audit Fields
                audit_data = {
                    "corp_id": str(val.get('corp_id')),
                    "provider_code": str(val.get('provider_code')),
                    "user_id": str(val.get('user_id', '') or "SYSTEM"),
                    "request_object": smart_payload,
                    "status_code": int(status_code),
                    "smart_response": res_data
                }

                if is_ok:
                    # Success model uses CharField for category
                    ProviderRestrictionSyncSuccess.objects.create(
                        **audit_data,
                        smart_restriction_category=cat_raw
                    )
                else:
                    # Failure model uses JSONField for category: convert to list for safety
                    cat_json = cat_raw.split(',') if ',' in cat_raw else [cat_raw]
                    
                    ProviderRestrictionSyncFailure.objects.create(
                        **audit_data,
                        smart_restriction_category=cat_json
                    )

            return is_ok
        except Exception as e:
            print(f"❌ Atomic Rollback for Restriction ID {idx}: {e}")
            return False