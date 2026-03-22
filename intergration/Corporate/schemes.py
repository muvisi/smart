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
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from requests.exceptions import RequestException
from engine.models import ApiSyncLog

logger = logging.getLogger(__name__)

class SmartSyncTaskService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.smart_token = None

    def _get_smart_token(self):
        """Authenticates with SMART API."""
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
        except Exception as e:
            logger.error(f"SMART Auth Failure: {str(e)}")
            return None

    def run_sync(self):
        """Executes the sync task for Retail and Corporate schemes."""
        stats = {"total": 0, "success": 0, "failed": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as cursor:
                # 1. Fetch data from MSSQL
                cursor.execute("SELECT * FROM dbo.smart_schemes_new")
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                
                if not rows:
                    return {"status": "skipped", "message": "No schemes pending sync."}

                # Convert rows to a list of dicts (JSON-like structure)
                schemes = [dict(zip(columns, row)) for row in rows]
                stats["total"] = len(schemes)

                # 2. Authenticate
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "Authentication failed."}

                for scheme in schemes:
                    # Prepare specific JSON payload
                    payload = {
                        'companyName': scheme.get('scheme_name'),
                        'clnPolCode': str(scheme.get('corp_id')),
                        'startDate': str(scheme.get('start_date')),
                        'endDate': str(scheme.get('end_date')),
                        'polTypeId': scheme.get('scheme_type_id'),
                        'userId': scheme.get('user_id'),
                        'anniv': scheme.get('anniv'),
                        'policyCurrencyId': "KES",
                        'countryCode': "KE",
                        'customerid': settings.SMART_CUSTOMER_ID
                    }

                    # Determine sync type for logging
                    is_retail = str(scheme.get('scheme_type')).upper() != 'CORPORATE'
                    transaction_label = "Retail Scheme" if is_retail else "Corporate Scheme"

                    # Initialize Audit Log (PostgreSQL)
                    sync_log = ApiSyncLog(
                        api_name="SyncHaisToSmart",
                        transaction_name=transaction_label,
                        request_object=payload, 
                        status=2 # Default to Fail
                    )

                    try:
                        # 3. Post to SMART API using JSON
                        api_url = f"{settings.SMART_API_BASE_URL}schemes"
                        
                        # We pass 'json=payload' to ensure requests handles the JSON serialization
                        res = requests.post(
                            api_url, 
                            json=payload, 
                            headers={
                                "Authorization": f"Bearer {self.smart_token}",
                                "Content-Type": "application/json"
                            }, 
                            verify=False, 
                            timeout=25
                        )
                        
                        sync_log.http_code = res.status_code
                        sync_log.response_object = res.json()
                        
                        # Logic check for SMART's 'successful' flag
                        success_flag = sync_log.response_object.get('successful')
                        is_successful = str(success_flag).lower() == 'true'
                        
                        sync_log.status = 1 if is_successful else 2

                        # 4. Atomic Update on MSSQL
                        with transaction.atomic(using=self.mssql_alias):
                            status_val = sync_log.status
                            cid = scheme.get('corp_id')
                            anniv = scheme.get('anniv')

                            if not is_retail:
                                # Corporate Update
                                cursor.execute(
                                    "UPDATE dbo.corp_anniversary SET sync = %s WHERE corp_id = %s AND anniv = %s",
                                    [status_val, cid, anniv]
                                )
                                cursor.execute("UPDATE dbo.corporate SET sync = %s WHERE corp_id = %s", [status_val, cid])
                            else:
                                # Retail Update
                                cursor.execute("UPDATE dbo.retail SET sync = %s WHERE corp_id = %s", [status_val, cid])

                        if is_successful: stats["success"] += 1
                        else: stats["failed"] += 1

                    except Exception as e:
                        logger.error(f"Processing error for {scheme.get('corp_id')}: {str(e)}")
                        sync_log.response_object = {"error": str(e)}
                        stats["failed"] += 1
                    
                    finally:
                        sync_log.save() # Save log to Postgres

            return {"status": "success", "stats": stats}

        except Exception as e:
            logger.critical(f"Task Failure: {str(e)}")
            return {"status": "error", "message": str(e)}