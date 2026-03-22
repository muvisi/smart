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
import urllib3
from urllib.parse import urlencode
from django.db import connections, transaction
from django.conf import settings
from engine.models import BenefitSyncSuccess, BenefitSyncFailure

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartRetailBenefitSyncService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        # self.hais_api = settings.HAIS_API_URL
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
            print(f"❌ SMART Retail Benefit Auth Error: {e}")
            return None

    def run_benefit_sync(self, hais_token):
        """Fetches from smart_retail_benefits_new and Syncs via URL Parameters."""
        print("\n💎 RETAIL BENEFIT SYNC STARTED")
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        hais_headers = {
            "Authorization": f"Bearer {hais_token}",
            "Content-Type": "application/json"
        }

        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetch data
                mssql_cursor.execute("SELECT TOP 50 * FROM dbo.smart_retail_benefits_new")
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    print(">>> SYNC: No retail benefits pending.")
                    return {"status": "success", "message": "No records."}

                benefits_json = [dict(zip(columns, row)) for row in rows]
                sync_stats["total"] = len(benefits_json)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for benefit_data in benefits_json:
                    if self._sync_single_benefit(mssql_cursor, benefit_data, hais_headers):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            print(f"✅ RETAIL BENEFIT DONE → Success: {sync_stats['success']}, Failed: {sync_stats['failed']}\n")
            return {"status": "success", "stats": sync_stats}

        except Exception as e:
            print(f"!!! Global Retail Benefit Sync Failure: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _sync_single_benefit(self, mssql_cursor, val, hais_headers):
        # 1. Mapping and Formatting
        family_no = str(val.get('category_id') or "")
        benefit_id = str(val.get('benefit_id') or "")
        anniv = str(val.get('anniv') or "")
        policy_no = str(val.get('scheme_id') or "")
        category_full = f"{val.get('category_name')}-{anniv}"
        
        ben_linked = str(val.get('sub_limit_of'))
        ben_linked_tq = "-" if (ben_linked == "0" or not ben_linked) else ben_linked

        # 2. Prepare Payload (Force all to String for URL encoding)
        smart_payload = {
            'benefitDesc': str(val.get('benefit_name', "")),
            'policyNumber': policy_no,
            'benTypeId': str(val.get('benefit_sharing', "")),
            'subLimitAmt': str(val.get('limit', "0")),
            'serviceType': str(val.get('service_type', "")),
            'memAssignedBenefit': str(val.get('member_assigned_benefit', "")),
            'clnPolCode': policy_no,
            'catCode': category_full,
            'clnBenCode': benefit_id,
            'benTypDesc': str(val.get('benefit_sharing_descr', "")),
            'benLinked2Tqcode': str(ben_linked_tq),
            'userId': str(val.get('user_id') or "SYSTEM"),
            'countrycode': "KE",
            'customerid': str(settings.SMART_CUSTOMER_ID)
        }

        # 3. API Post (URL Parameters logic)
        res_json = {}
        status_code = 500
        is_ok = False
        
        try:
            encoded_url = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(smart_payload)}"
            res = self.session.post(
                encoded_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                timeout=60
            )
            status_code = res.status_code
            try:
                res_json = res.json()
            except:
                res_json = {"raw_response": res.text}
                
            is_ok = str(res_json.get('successful', '')).lower() == 'true'
            
            if is_ok:
                print(f"✅ Success: Benefit {benefit_id} for {family_no}")
            else:
                print(f"❌ Rejected: {benefit_id} - {res_json.get('status_msg')}")

        except Exception as e:
            print(f"!!! SMART API Error for {benefit_id}: {e}")
            res_json = {"error": str(e)}

        # 4. Database Transactions
        try:
            with transaction.atomic(using='default'):
                # Audit Trail (Mapping family_no to corp_id for model compliance)
                LogModel = BenefitSyncSuccess if is_ok else BenefitSyncFailure
                LogModel.objects.create(
                    corp_id=family_no,
                    category=category_full,
                    anniv=anniv,
                    benefit_id=benefit_id,
                    benefit_name=str(val.get('benefit_name')),
                    request_object=smart_payload,
                    policy_no=policy_no,
                    smart_status=int(status_code),
                    smart_response=res_json
                )

                # Update MSSQL Table: member_benefits
                sync_status = 1 if is_ok else 3
                mssql_cursor.execute(
                    "UPDATE dbo.member_benefits SET sync = %s WHERE member_no LIKE %s AND anniv = %s AND benefit = %s",
                    [sync_status, f"%{family_no}%", anniv, benefit_id]
                )

            # 5. Post back to HAIS Log
            try:
                self.session.post(self.hais_api, json={
                    "name": "createApiLog",
                    "param": {
                        "source": "HAIS-SMART",
                        "transactionName": "Retail Benefit Sync",
                        "statusCode": status_code,
                        "requestObject": [val],
                        "responseObject": [res_json]
                    }
                }, headers=hais_headers, timeout=10)
            except:
                pass # Prevent HAIS logging failures from killing the sync loop

            return is_ok
        except Exception as e:
            print(f"❌ Sync Coordination Error for {benefit_id}: {str(e)}")
            return False