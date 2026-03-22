import requests
import logging
import uuid
from urllib.parse import urlencode
from django.db import connections, transaction
from django.conf import settings

# Audit Trail Models
from engine.models import BenefitSyncSuccess, BenefitSyncFailure

logger = logging.getLogger(__name__)

class SmartRetailBenefitSyncService:
    def __init__(self):
        self.mssql_alias = 'external_mssql'
        self.smart_token = None
        self.hais_api = settings.HAIS_API_URL

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

    def run_benefit_sync(self, hais_token):
        """
        Main execution: Fetches from MSSQL View and Syncs to SMART
        """
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        headers = {
            "Authorization": f"Bearer {hais_token}",
            "Content-Type": "application/json"
        }

        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch pending benefits from MSSQL View
                mssql_cursor.execute("SELECT TOP 50 * FROM dbo.smart_retail_benefits_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No benefits pending in MSSQL."}

                sync_stats["total"] = len(rows)
                
                # 2. Get SMART Access Token
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                # 3. Process each row
                # Converting rows to dictionaries for easier mapping
                for row_data in [dict(zip(columns, r)) for r in rows]:
                    success = self._sync_single_benefit(mssql_cursor, row_data, headers)
                    if success:
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}

        except Exception as e:
            logger.critical(f"Global Benefit Sync Failure: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _sync_single_benefit(self, mssql_cursor, val, hais_headers):
        # Extract Variables from MSSQL Row
        corp_id = str(val.get('category_id'))
        benefit_id = str(val.get('benefit_id'))
        benefit_name = val.get('benefit_name')
        anniv = str(val.get('anniv'))
        policy_no = val.get('scheme_id')
        category_full = f"{val.get('category_name')}-{anniv}"

        # Logic for sub-limits
        ben_linked = val.get('sub_limit_of')
        ben_linked_tq = "-" if (ben_linked == "0" or not ben_linked) else ben_linked

        # Construct SMART Payload (Audit: request_object)
        smart_payload = {
            'benefitDesc': benefit_name,
            'policyNumber': policy_no,
            'benTypeId': val.get('benefit_sharing'),
            'subLimitAmt': val.get('limit'),
            'serviceType': val.get('service_type'),
            'memAssignedBenefit': val.get('member_assigned_benefit'),
            'clnPolCode': policy_no,
            'catCode': category_full,
            'clnBenCode': benefit_id,
            'benTypDesc': val.get('benefit_sharing_descr'),
            'benLinked2Tqcode': ben_linked_tq,
            'userId': val.get('user_id'),
            'countrycode': "KE",
            'customerid': settings.SMART_CUSTOMER_ID
        }

        # 1. API Post to SMART
        try:
            smart_url = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(smart_payload)}"
            res = requests.post(
                smart_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                verify=False, 
                timeout=25
            )
            smart_response_json = res.json()
            is_ok = smart_response_json.get('successful') is True
            http_code = res.status_code
        except Exception as e:
            is_ok, http_code, smart_response_json = False, 500, {"error": str(e)}

        # 2. Database Coordination (Audit Trail + MSSQL Update)
        try:
            with transaction.atomic(using='default'):
                # Log to Postgres Audit Trail
                LogModel = BenefitSyncSuccess if is_ok else BenefitSyncFailure
                LogModel.objects.using('default').create(
                    corp_id=corp_id,
                    category=category_full,
                    anniv=anniv,
                    benefit_id=benefit_id,
                    benefit_name=benefit_name,
                    request_object=smart_payload,
                    policy_no=policy_no,
                    smart_status=http_code,
                    smart_response=smart_response_json
                )

                # Update Sync Status in MSSQL member_benefits
                sync_status = 1 if is_ok else 3
                family_no_like = f"%{corp_id}%"
                
                mssql_cursor.execute(
                    """
                    UPDATE member_benefits 
                    SET sync = %s 
                    WHERE member_no LIKE %s AND anniv = %s AND benefit = %s
                    """, 
                    [sync_status, family_no_like, anniv, benefit_id]
                )

            # 3. Optional: Post log back to HAIS if required by your architecture
            log_payload = {
                "name": "createApiLog",
                "param": {
                    "source": "HAIS-SMART",
                    "transactionName": "Retail Scheme Benefit",
                    "statusCode": http_code,
                    "requestObject": [val],
                    "responseObject": [smart_response_json]
                }
            }
            requests.post(self.hais_api, json=log_payload, headers=hais_headers, timeout=10)

            return is_ok

        except Exception as e:
            logger.error(f"Atomic Update Failed for {benefit_id}: {str(e)}")
            return False
        
import json
import requests
import logging
from urllib.parse import urlencode
from django.db import connections, transaction
from django.conf import settings
from engine.models import BenefitSyncSuccess, BenefitSyncFailure

logger = logging.getLogger(__name__)

class SmartBenefitSyncService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.smart_token = None
        self.hais_api = settings.HAIS_API_URL
        self.session = requests.Session() # Reuse connection for performance
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

    def run_benefit_sync(self, hais_token):
        """Main execution: Fetches from MSSQL View and Syncs to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        headers = {
            "Authorization": f"Bearer {hais_token}",
            "Content-Type": "application/json"
        }

        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch data in JSON-friendly format
                mssql_cursor.execute("SELECT TOP 50 * FROM dbo.smart_retail_benefits_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No benefits pending."}

                # Conversion to JSON objects (list of dicts)
                benefits_json = [dict(zip(columns, row)) for row in rows]
                sync_stats["total"] = len(benefits_json)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for benefit_data in benefits_json:
                    if self._sync_single_benefit(mssql_cursor, benefit_data, headers):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}

        except Exception as e:
            logger.critical(f"Benefit Sync Engine Failure: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _sync_single_benefit(self, mssql_cursor, val, hais_headers):
        # Mapping variables
        corp_id = str(val.get('category_id'))
        benefit_id = str(val.get('benefit_id'))
        anniv = str(val.get('anniv'))
        policy_no = val.get('scheme_id')
        category_full = f"{val.get('category_name')}-{anniv}"
        
        ben_linked = val.get('sub_limit_of')
        ben_linked_tq = "-" if (ben_linked == "0" or not ben_linked) else ben_linked

        # Payload
        smart_payload = {
            'benefitDesc': val.get('benefit_name'),
            'policyNumber': policy_no,
            'benTypeId': val.get('benefit_sharing'),
            'subLimitAmt': val.get('limit'),
            'serviceType': val.get('service_type'),
            'memAssignedBenefit': val.get('member_assigned_benefit'),
            'clnPolCode': policy_no,
            'catCode': category_full,
            'clnBenCode': benefit_id,
            'benTypDesc': val.get('benefit_sharing_descr'),
            'benLinked2Tqcode': ben_linked_tq,
            'userId': val.get('user_id'),
            'countrycode': "KE",
            'customerid': settings.SMART_CUSTOMER_ID
        }

        # 1. Post to SMART (100s Timeout)
        try:
            params = {'country': "KE", 'customerid': settings.SMART_CUSTOMER_ID}
            smart_url = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(params)}"
            
            res = self.session.post(smart_url, json=smart_payload, timeout=100)
            status_code = res.status_code
            res_json = res.json()
            is_ok = res_json.get('successful') is True
        except Exception as e:
            is_ok, status_code, res_json = False, 500, {"error": str(e)}

        # 2. Database Transactions
        try:
            with transaction.atomic(using='default'):
                # Audit Trail (PostgreSQL)
                Model = BenefitSyncSuccess if is_ok else BenefitSyncFailure
                Model.objects.create(
                    corp_id=corp_id,
                    category=category_full,
                    anniv=anniv,
                    benefit_id=benefit_id,
                    benefit_name=val.get('benefit_name'),
                    request_object=smart_payload,
                    policy_no=policy_no,
                    smart_status=status_code,
                    smart_response=res_json
                )

                # Update MSSQL Table: member_benefits
                sync_status = 1 if is_ok else 3
                mssql_cursor.execute(
                    "UPDATE member_benefits SET sync = %s WHERE member_no LIKE %s AND anniv = %s AND benefit = %s",
                    [sync_status, f"%{corp_id}%", anniv, benefit_id]
                )

            # 3. Post back to HAIS Log (Async friendly)
            self.session.post(self.hais_api, json={
                "name": "createApiLog",
                "param": {
                    "source": "HAIS-SMART",
                    "transactionName": "Retail Scheme Benefit",
                    "statusCode": status_code,
                    "requestObject": [val],
                    "responseObject": [res_json]
                }
            }, headers=hais_headers, timeout=15)

            return is_ok
        except Exception as e:
            logger.error(f"Sync Coordination Error for {benefit_id}: {str(e)}")
            return False