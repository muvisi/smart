import requests
import logging
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings

from intergration.models import CopaySyncFailure, CopaySyncSuccess
# from .models import CopaySyncSuccess, CopaySyncFailure

logger = logging.getLogger(__name__)

class SmartCopaySyncService:
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
            logger.error(f"SMART Copay Auth Failure: {str(e)}")
            return None

    def run_copay_sync(self):
        """Syncs Corporate Scheme Copays from MSSQL to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch new copays as per PHP logic
                mssql_cursor.execute("SELECT TOP 20* FROM dbo.smart_corp_copay_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No copays to sync."}

                sync_stats["total"] = len(rows)
                self.smart_token = self._get_smart_token()
                
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for row in rows:
                    val = dict(zip(columns, row))
                    success = self._process_copay(mssql_cursor, val)
                    
                    if success:
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            logger.error(f"MSSQL Connection Error (Copays): {str(e)}")
            return {"status": "error", "message": "Database connection failed."}

    def _process_copay(self, mssql_cursor, val):
        """Handles Transformation, API call, and Atomic Audit Logging."""
        
        # 1. Prepare Payload
        smart_payload = {
            "integ_scheme_code": str(val.get('corp_id')),
            "integ_cat_code": str(val.get('smart_copay_category')),
            "integ_ben_code": str(val.get('benefit_code')),
            "integ_prov_code": str(val.get('provider_code')),
            "integ_service_code": str(val.get('service_code')),
            "copay_type": int(val.get('copay_type', 0)),
            "amount": float(val.get('copay_amt', 0.0))
        }

        # 2. API Call (Outside Transaction)
        res_data = {}
        status_code = 500
        try:
            params = {'country': "KE", 'customerid': settings.SMART_CUSTOMER_ID}
            api_url = f"{settings.SMART_API_BASE_URL}copay/setup?{urlencode(params)}"
            
            res = requests.post(
                api_url, 
                json=smart_payload, # Note: PHP used raw string, JSON is better here
                headers={
                    "Authorization": f"Bearer {self.smart_token}",
                    "customerid": settings.SMART_CUSTOMER_ID,
                    "country": "KE"
                }, 
                verify=False, 
                timeout=25
            )
            status_code = res.status_code
            res_data = res.json()
            is_ok = res_data.get('successful') is True
        except Exception as e:
            is_ok = False
            res_data = {"error": str(e)}

        # 3. Atomic Update Block
        try:
            with transaction.atomic(using=self.audit_db):
                # Status Mapping: Success = 1, Failure = 2 (as per PHP logic)
                sync_status = 1 if is_ok else 2

                # Update corp_provider table (MSSQL)
                update_query = "UPDATE corp_provider SET sync = %s WHERE idx = %s"
                mssql_cursor.execute(update_query, [sync_status, val.get('idx')])

                # Log Audit Details
                audit_fields = {
                    "corp_id": val.get('corp_id'),
                    "category": val.get('smart_copay_category'),
                    "benefit": val.get('benefit_code'),
                    "provider": val.get('provider_code'),
                    "service": val.get('service_code'),
                    "copay_amount": float(val.get('copay_amt', 0.0)),
                    "request_object": smart_payload,
                    "smart_status": status_code,
                    "smart_response": res_data
                }

                if is_ok:
                    CopaySyncSuccess.objects.create(**audit_fields)
                else:
                    CopaySyncFailure.objects.create(**audit_fields)

            return is_ok

        except Exception as e:
            logger.critical(f"Atomic Integrity Failure for Copay Record {val.get('idx')}: {str(e)}")
            return False
        
        
import json
import requests
import logging
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from intergration.models import CopaySyncSuccess, CopaySyncFailure

logger = logging.getLogger(__name__)

class SmartRetailCopaySyncService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.audit_db = 'default'  # PostgreSQL
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates with SMART API with a 15s timeout."""
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
            logger.error(f"SMART Retail Copay Auth Failure: {str(e)}")
            return None

    def run_sync(self):
        """Main entry point: Pulls Retail Copays from MSSQL and syncs to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch data in JSON-like structure
                mssql_cursor.execute("SELECT TOP 20 * FROM dbo.smart_retail_copay_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No retail copays pending sync."}

                # JSON-compliant mapping
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

                return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            logger.error(f"Retail Copay MSSQL Error: {str(e)}")
            return {"status": "error", "message": "External database connection failure."}

    def _process_record(self, mssql_cursor, val):
        """Handles Logic for a single Retail record sync with 120s timeout."""
        
        # 1. Prepare JSON Payload
        smart_payload = {
            "integ_scheme_code": str(val.get('retail_id')),
            "integ_cat_code": str(val.get('smart_copay_category')),
            "integ_ben_code": str(val.get('benefit_code')),
            "integ_prov_code": str(val.get('provider_code')),
            "integ_service_code": str(val.get('service_code')),
            "copay_type": int(val.get('copay_type', 0)),
            "amount": float(val.get('copay_amt', 0.0))
        }

        # 2. API Call (Strict 120s Timeout)
        is_ok = False
        status_code = 500
        res_data = {}
        
        try:
            api_params = {'country': "KE", 'customerid': settings.SMART_CUSTOMER_ID}
            api_url = f"{settings.SMART_API_BASE_URL}copay/setup?{urlencode(api_params)}"
            
            res = requests.post(
                api_url, 
                json=smart_payload, 
                headers={
                    "Authorization": f"Bearer {self.smart_token}", 
                    "Content-Type": "application/json"
                },
                verify=False, 
                timeout=120 # 120 second timeout as requested
            )
            status_code = res.status_code
            res_data = res.json()
            is_ok = str(res_data.get('successful')).lower() == 'true'
        except requests.exceptions.Timeout:
            res_data = {"error": "Timeout", "details": "The SMART API did not respond within 120s"}
        except Exception as e:
            res_data = {"error": "API Failure", "details": str(e)}

        # 3. DB Atomic Update & Audit
        try:
            with transaction.atomic(using=self.audit_db):
                # Update MSSQL Status (Retail Table)
                sync_status = 1 if is_ok else 2
                mssql_cursor.execute(
                    "UPDATE retail_provider SET sync = %s WHERE idx = %s", 
                    [sync_status, val.get('idx')]
                )

                # Prepare PostgreSQL Audit Fields
                audit_fields = {
                    "retail_id": val.get('retail_id'),
                    "category": val.get('smart_copay_category'),
                    "benefit": val.get('benefit_code'),
                    "provider": val.get('provider_code'),
                    "service": val.get('service_code'),
                    "copay_amount": float(val.get('copay_amt', 0.0)),
                    "request_object": smart_payload,
                    "smart_status": status_code,
                    "smart_response": res_data
                }

                if is_ok:
                    CopaySyncSuccess.objects.create(**audit_fields)
                else:
                    CopaySyncFailure.objects.create(**audit_fields)

            return is_ok
        except Exception as e:
            logger.critical(f"Critical DB Fail for Retail Index {val.get('idx')}: {str(e)}")
            return False