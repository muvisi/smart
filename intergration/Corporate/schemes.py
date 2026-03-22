import json
import requests
import logging
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from requests.exceptions import RequestException

from engine.models import ApiSyncLog
# from .models import ApiSyncLog

logger = logging.getLogger(__name__)

class SmartSyncService:
    def __init__(self):
        self.mssql_alias = settings.EXTERNAL_MSSQL_ALIAS
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates only when schemes are confirmed present."""
        auth_params = {
            'client_id': settings.SMART_CLIENT_ID,
            'client_secret': settings.SMART_CLIENT_SECRET,
            'grant_type': settings.SMART_GRANT_TYPE
        }
        try:
            url = f"{settings.SMART_ACCESS_TOKEN}{urlencode(auth_params)}"
            response = requests.post(url, verify=False, timeout=15)
            response.raise_for_status()
            token = response.json().get('access_token')
            if not token:
                raise ValueError("Access token missing in SMART response.")
            return token
        except RequestException as e:
            logger.error(f"SMART Auth Failure: {str(e)}")
            raise ConnectionError(f"Authentication failed: {str(e)}")

    def run_sync(self):
        """Main execution logic with early exit for zero schemes."""
        stats = {"total": 0, "success": 0, "failed": 0}
        
        try:
            # --- KEEN CHECK: Fetching data first ---
            with connections[self.mssql_alias].cursor() as cursor:
                cursor.execute("SELECT * FROM dbo.smart_schemes_new")
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                
                # SKIP EVERYTHING if no schemes found
                if not rows:
                    return {"status": "skipped", "message": "No schemes pending sync. System idle."}

                schemes = [dict(zip(columns, row)) for row in rows]
                stats["total"] = len(schemes)

                # --- DELAYED AUTH: Only get token if we actually have work to do ---
                self.smart_token = self._get_smart_token()

                for scheme in schemes:
                    # Capture exact payload for audit
                    payload = {
                        'companyName': scheme.get('scheme_name'),
                        'clnPolCode': scheme.get('corp_id'),
                        'startDate': scheme.get('start_date'),
                        'endDate': scheme.get('end_date'),
                        'polTypeId': scheme.get('scheme_type_id'),
                        'userId': scheme.get('user_id'),
                        'anniv': scheme.get('anniv'),
                        'policyCurrencyId': "KES",
                        'countryCode': "KE",
                        'customerid': settings.SMART_CUSTOMER_ID
                    }

                    # Prepare Audit Log
                    sync_log = ApiSyncLog(
                        api_name="SyncHaisToSmart",
                        transaction_name=f"{str(scheme.get('scheme_type')).capitalize()} Scheme",
                        request_object=payload,
                        status=2 # Default to Failure
                    )

                    try:
                        # 1. Post to SMART API
                        api_url = f"{settings.SMART_API_BASE_URL}schemes?{urlencode(payload)}"
                        res = requests.post(
                            api_url, 
                            headers={"Authorization": f"Bearer {self.smart_token}"}, 
                            verify=False, 
                            timeout=25
                        )
                        
                        sync_log.http_code = res.status_code
                        sync_log.response_object = res.json()
                        
                        is_successful = str(sync_log.response_object.get('successful', 'false')).lower() == 'true'
                        sync_log.status = 1 if is_successful else 2

                        # 2. Atomic Database Update (Direct SQL)
                        with transaction.atomic(using=self.mssql_alias):
                            corp_id = scheme.get('corp_id')
                            if str(scheme.get('scheme_type')).upper() == 'CORPORATE':
                                cursor.execute(
                                    "UPDATE dbo.corp_anniversary SET sync = %s WHERE corp_id = %s AND anniv = %s",
                                    [sync_log.status, corp_id, scheme.get('anniv')]
                                )
                                cursor.execute("UPDATE dbo.corporate SET sync = %s WHERE corp_id = %s", [sync_log.status, corp_id])
                            else:
                                cursor.execute("UPDATE dbo.retail SET sync = %s WHERE corp_id = %s", [sync_log.status, corp_id])

                        if is_successful: stats["success"] += 1
                        else: stats["failed"] += 1

                    except Exception as e:
                        logger.error(f"Sync Error for {scheme.get('corp_id')}: {str(e)}")
                        sync_log.status = 2
                        sync_log.response_object = {"exception_error": str(e)}
                        stats["failed"] += 1
                    
                    finally:
                        # 3. Persistent Local Log
                        sync_log.save()

            return {"status": "success", "stats": stats}

        except DatabaseError as db_e:
            logger.error(f"MSSQL Connection Error: {str(db_e)}")
            return {"status": "error", "message": "Remote Database Unavailable"}
        except Exception as e:
            logger.critical(f"Critical System Failure: {str(e)}")
            return {"status": "error", "message": str(e)}
        
        
import json
import requests
import logging
import urllib3
from urllib.parse import urlencode
from datetime import datetime
from django.db import connections, transaction
from django.conf import settings
from engine.models import ApiSyncLog

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartSyncTaskService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates with SMART API using form-urlencoded data."""
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
        print("🔄 DB SCHEMES SYNC STARTED (CELERY TASK)")
        
        smart_token = self._get_smart_token()
        if not smart_token:
            print("❌ Failed to get SMART token")
            return {"status": "error", "message": "Auth failed"}

        stats = {"total": 0, "success": 0, "failed": 0}

        try:
            with connections[self.mssql_alias].cursor() as cursor:
                # 1. Fetch data from MSSQL
                cursor.execute("SELECT * FROM dbo.smart_schemes_new")
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                
                if not rows:
                    print(">>> SYNC: No records found.")
                    return {"status": "skipped", "message": "No schemes pending."}

                stats["total"] = len(rows)

                for row in rows:
                    scheme = dict(zip(columns, row))
                    
                    # 2. Prepare Payload for URL Encoding
                    # Note: We use 'customerid' lowercase as per your logic file
                    payload = {
                        "companyName": str(scheme.get("scheme_name") or ""),
                        "clnPolCode": str(scheme.get("corp_id", "")),
                        "startDate": str(scheme.get("start_date", "")),
                        "endDate": str(scheme.get("end_date", "")),
                        "polTypeId": str(scheme.get("scheme_type_id", "")),
                        "userId": str(scheme.get("user_id") or "SYSTEM"),
                        "anniv": str(scheme.get("anniv", "")),
                        "policyCurrencyId": getattr(settings, "POLICY_CURRENCY_ID", "KES"),
                        "countryCode": getattr(settings, "COUNTRY_CODE", "KE"),
                        "customerid": settings.SMART_CUSTOMER_ID
                    }

                    # 3. Construct URL with Query Params
                    encoded_params = urlencode(payload)
                    api_url = f"{settings.SMART_API_BASE_URL}schemes?{encoded_params}"

                    print(f"\n💡 SENDING TO SMART (ID: {payload['clnPolCode']})")
                    print(f"URL: {api_url}")

                    is_retail = str(scheme.get('scheme_type', '')).upper() != 'CORPORATE'
                    sync_log = ApiSyncLog(
                        api_name="SyncDBToSmart",
                        transaction_name=f"{'Retail' if is_retail else 'Corporate'} Scheme: {payload['companyName']}",
                        request_object=payload,
                        status=2 
                    )

                    try:
                        # 4. POST request (Data is in the URL, not the body)
                        resp = requests.post(
                            api_url,
                            headers={"Authorization": f"Bearer {smart_token}"},
                            verify=False,
                            timeout=60
                        )

                        try:
                            res_data = resp.json()
                        except:
                            res_data = {"raw_response": resp.text}

                        sync_log.http_code = resp.status_code
                        sync_log.response_object = res_data
                        
                        is_successful = res_data.get("successful") is True
                        sync_log.status = 1 if is_successful else 2

                        # 5. Update MSSQL Sync Status
                        with transaction.atomic(using=self.mssql_alias):
                            cid = scheme.get('corp_id')
                            anniv = scheme.get('anniv')
                            status_val = sync_log.status

                            if not is_retail:
                                # Corporate logic
                                cursor.execute("UPDATE dbo.corp_anniversary SET sync=%s WHERE corp_id=%s AND anniv=%s", [status_val, cid, anniv])
                                cursor.execute("UPDATE dbo.corporate SET sync=%s WHERE corp_id=%s", [status_val, cid])
                            else:
                                # Retail logic
                                cursor.execute("UPDATE dbo.retail SET sync=%s WHERE corp_id=%s", [status_val, cid])

                        if is_successful:
                            print(f"✅ scheme posted: {payload['clnPolCode']} Status: {sync_log.status}")
                            stats["success"] += 1
                        else:
                            print(f"❌ scheme rejected: {payload['clnPolCode']} Status: {sync_log.status}")
                            stats["failed"] += 1

                    except Exception as e:
                        print(f"❌ SMART ERROR for {scheme.get('corp_id')}: {e}")
                        stats["failed"] += 1
                    finally:
                        sync_log.save()

            print(f"✅ DONE → Success: {stats['success']}, Failed: {stats['failed']}")
            return {"status": "success", "stats": stats}

        except Exception as e:
            print(f"!!! CRITICAL FAILURE: {str(e)}")
            return {"status": "error", "message": str(e)}