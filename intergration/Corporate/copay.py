import json
import requests
import urllib3
import logging
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from intergration.models import CopaySyncSuccess, CopaySyncFailure

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartRetailCopaySyncService:
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
            print(f"❌ SMART Retail Copay Auth Error: {e}")
            return None

    def run_sync(self):
        """Pulls Retail Copays from MSSQL and syncs to SMART."""
        print("\n💰 RETAIL COPAY SYNC STARTED")
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                mssql_cursor.execute("SELECT TOP 20 * FROM dbo.smart_retail_copay_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    print(">>> SYNC: No retail copays pending.")
                    return {"status": "success", "message": "No records."}

                records = [dict(zip(columns, row)) for row in rows]
                sync_stats["total"] = len(records)

                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for record in records:
                    if self._process_record(mssql_cursor, record):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

                print(f"✅ RETAIL COPAY DONE → Success: {sync_stats['success']}, Failed: {sync_stats['failed']}\n")
                return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            print(f"❌ Retail Copay MSSQL Error: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _process_record(self, mssql_cursor, val):
        idx = val.get('idx')
        smart_payload = {
            "integ_scheme_code": str(val.get('retail_id', '')),
            "integ_cat_code": str(val.get('smart_copay_category', '')),
            "integ_ben_code": str(val.get('benefit_code', '')),
            "integ_prov_code": str(val.get('provider_code', '')),
            "integ_service_code": str(val.get('service_code', '')),
            "copay_type": str(val.get('copay_type', '0')),
            "amount": str(val.get('copay_amt', '0.0'))
        }

        is_ok = False
        status_code = 500
        res_data = {}
        
        try:
            api_params = {'country': "KE", 'customerid': settings.SMART_CUSTOMER_ID}
            api_url = f"{settings.SMART_API_BASE_URL}copay/setup?{urlencode(api_params)}"
            
            res = self.session.post(
                api_url, 
                json=smart_payload, 
                headers={"Authorization": f"Bearer {self.smart_token}"},
                timeout=120 
            )
            status_code = res.status_code
            res_data = res.json()
            is_ok = str(res_data.get('successful', '')).lower() == 'true'
        except Exception as e:
            res_data = {"error": str(e)}

        try:
            with transaction.atomic(using=self.audit_db):
                sync_status = 1 if is_ok else 2
                mssql_cursor.execute("UPDATE dbo.retail_provider SET sync = %s WHERE idx = %s", [sync_status, idx])

                audit_fields = {
                    "retail_id": str(val.get('retail_id')),
                    "category": str(val.get('smart_copay_category')),
                    "benefit": str(val.get('benefit_code')),
                    "provider": str(val.get('provider_code')),
                    "service": str(val.get('service_code')),
                    "copay_amount": float(val.get('copay_amt', 0.0)),
                    "request_object": smart_payload,
                    "smart_status": int(status_code),
                    "smart_response": res_data
                }

                if is_ok:
                    CopaySyncSuccess.objects.create(**audit_fields)
                    print(f"✅ Success: Retail Copay ID {idx}")
                else:
                    CopaySyncFailure.objects.create(**audit_fields)
                    print(f"❌ Failed: Retail Copay ID {idx}")

            return is_ok
        except Exception as e:
            print(f"❌ DB Failure for Retail Copay {idx}: {e}")
            return False