import requests
import logging
import uuid
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from engine.models import BenefitSyncSuccess, BenefitSyncFailure

logger = logging.getLogger(__name__)

class SmartBenefitSyncService:
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
            logger.error(f"SMART Benefit Auth Failure: {str(e)}")
            return None

    def run_benefit_sync(self):
        """Syncs Corporate Scheme Benefits from MSSQL to SMART."""
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Select unsynced records from the smart_bens view
                query = "SELECT * FROM dbo.smart_bens WHERE synced IS NULL"
                mssql_cursor.execute(query)
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    return {"status": "success", "message": "No benefits to sync."}

                sync_stats["total"] = len(rows)
                self.smart_token = self._get_smart_token()
                
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for row in rows:
                    val = dict(zip(columns, row))
                    success = self._process_benefit(mssql_cursor, val)
                    
                    if success:
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            logger.error(f"Benefit Sync MSSQL Connection Error: {str(e)}")
            return {"status": "error", "message": "Source database connection failed."}

    def _process_benefit(self, mssql_cursor, val):
        """Handles Transformation, API Call, and Atomic Database Update."""
        # 1. Logic Transformation
        ben_linked = str(val.get('sub_limit_of'))
        tq_code = "-" if ben_linked == "0" else ben_linked

        smart_payload = {
            'benefitDesc': val.get('benefit_name'),
            'policyNumber': val.get('policy_no'),
            'benTypeId': val.get('benefit_sharing'),
            'subLimitAmt': val.get('limit'),
            'serviceType': val.get('benefit_class'),
            'memAssignedBenefit': val.get('member_assigned_benefit'),
            'clnPolCode': val.get('corp_id'),
            'catCode': f"{val.get('category_name')}-{val.get('anniv')}",
            'clnBenCode': val.get('benefit_id'),
            'benTypDesc': val.get('benefit_sharing_descr'),
            'benLinked2Tqcode': tq_code,
            'userId': val.get('user_id'),
            'countrycode': "KE",
            'customerid': settings.SMART_CUSTOMER_ID
        }

        # 2. API Call (Outside Transaction)
        res_data = {}
        status_code = 500
        try:
            api_url = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(smart_payload)}"
            res = requests.post(
                api_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                verify=False, 
                timeout=25
            )
            status_code = res.status_code
            res_data = res.json()
            is_ok = res_data.get('successful') is True
        except Exception as e:
            is_ok = False
            res_data = {"error": "API/Network Failure", "details": str(e)}

        # 3. Atomic Update and Audit Trail
        try:
            with transaction.atomic(using=self.audit_db):
                # Status Mapping: Success = 1, Failure = 3
                sync_status = 1 if is_ok else 3

                # Update corp_groups (MSSQL)
                update_query = """
                    UPDATE corp_groups 
                    SET sync = %s 
                    WHERE corp_id = %s 
                      AND anniv = %s 
                      AND category = %s 
                      AND benefit = %s
                """
                mssql_cursor.execute(update_query, [
                    sync_status, 
                    val.get('corp_id'), 
                    val.get('anniv'), 
                    val.get('category_name'),
                    val.get('benefit_id')
                ])

                # Audit Entry
                audit_fields = {
                    "corp_id": val.get('corp_id'),
                    "category": val.get('category_name'),
                    "anniv": val.get('anniv'),
                    "benefit_id": val.get('benefit_id'),
                    "benefit_name": val.get('benefit_name'),
                    "policy_no": val.get('policy_no'),
                    "request_object": smart_payload,
                    "smart_status": status_code,
                    "smart_response": res_data
                }

                if is_ok:
                    BenefitSyncSuccess.objects.create(**audit_fields)
                else:
                    BenefitSyncFailure.objects.create(**audit_fields)

            return is_ok

        except Exception as e:
            logger.critical(f"Atomic Rollback for Benefit {val.get('benefit_id')}: {str(e)}")
            return False
import json
import requests
import logging
import urllib3
from urllib.parse import urlencode
from django.db import connections, transaction, DatabaseError
from django.conf import settings
from engine.models import BenefitSyncSuccess, BenefitSyncFailure

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class SmartBenefitSyncService:
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
            print(f"❌ SMART Benefit Auth Error: {e}")
            return None

    def run_benefit_sync(self):
        """Syncs Benefits (Retail/Corp) via URL Parameters."""
        print("\n💎 BENEFIT SYNC STARTED")
        sync_stats = {"success": 0, "failed": 0, "total": 0}
        
        try:
            with connections[self.mssql_alias].cursor() as mssql_cursor:
                # 1. Fetching pending benefits
                query = "SELECT * FROM dbo.smart_bens WHERE synced IS NULL"
                mssql_cursor.execute(query)
                columns = [col[0] for col in mssql_cursor.description]
                rows = mssql_cursor.fetchall()

                if not rows:
                    print(">>> SYNC: No benefits found in dbo.smart_bens")
                    return {"status": "success", "message": "No benefits to sync."}

                benefits = [dict(zip(columns, row)) for row in rows]
                sync_stats["total"] = len(benefits)
                
                self.smart_token = self._get_smart_token()
                if not self.smart_token:
                    return {"status": "error", "message": "SMART Auth failed."}

                for benefit in benefits:
                    if self._process_benefit(mssql_cursor, benefit):
                        sync_stats["success"] += 1
                    else:
                        sync_stats["failed"] += 1

            print(f"✅ BENEFIT DONE → Success: {sync_stats['success']}, Failed: {sync_stats['failed']}\n")
            return {"status": "success", "stats": sync_stats}

        except DatabaseError as e:
            print(f"❌ Benefit Sync Database Error: {str(e)}")
            return {"status": "error", "message": "External MSSQL connection failed."}

    def _process_benefit(self, mssql_cursor, val):
        """Handles URL Transformation, API Call, and Audit."""
        ben_linked = str(val.get('sub_limit_of'))
        tq_code = "-" if ben_linked == "0" else ben_linked
        is_retail = str(val.get('scheme_type', '')).upper() != 'CORPORATE'
        cat_code = f"{val.get('category_name')}-{val.get('anniv')}"

        # 1. Prepare Payload (Force all values to String for URL encoding)
        smart_payload = {
            'benefitDesc': str(val.get('benefit_name', "")),
            'policyNumber': str(val.get('policy_no', "")),
            'benTypeId': str(val.get('benefit_sharing', "")),
            'subLimitAmt': str(val.get('limit', "0.0")),
            'serviceType': str(val.get('benefit_class', "")),
            'memAssignedBenefit': str(val.get('member_assigned_benefit', "")),
            'clnPolCode': str(val.get('corp_id', "")),
            'catCode': str(cat_code),
            'clnBenCode': str(val.get('benefit_id', "")),
            'benTypDesc': str(val.get('benefit_sharing_descr', "")),
            'benLinked2Tqcode': str(tq_code),
            'userId': str(val.get('user_id', "") or "SYSTEM"),
            'countrycode': "KE",
            'customerid': str(settings.SMART_CUSTOMER_ID)
        }

        # 2. Construct URL with Query Params
        encoded_params = urlencode(smart_payload)
        api_url = f"{settings.SMART_API_BASE_URL}benefits?{encoded_params}"

        print(f"---> DISPATCHING BENEFIT: {val.get('benefit_id')} for Cat: {cat_code}")

        res_data = {}
        status_code = 500
        is_ok = False
        
        try:
            # 3. API Call (Data in URL)
            res = requests.post(
                api_url, 
                headers={"Authorization": f"Bearer {self.smart_token}"}, 
                verify=False, 
                timeout=45 
            )
            status_code = res.status_code
            
            try:
                res_data = res.json()
            except:
                res_data = {"raw_response": res.text}
                
            is_ok = str(res_data.get('successful')).lower() == 'true'
            
            if is_ok:
                print(f"✅ Success: Benefit {val.get('benefit_id')}")
            else:
                print(f"❌ Rejected: {val.get('benefit_id')} - {res_data.get('status_msg')}")

        except Exception as e:
            print(f"!!! API Error for Benefit {val.get('benefit_id')}: {e}")
            res_data = {"error": "API communication failure", "details": str(e)}

        # 4. Atomic Database Update and Audit
        try:
            with transaction.atomic(using=self.audit_db):
                # 1 = Success, 3 = Failed (as per your original logic)
                sync_status = 1 if is_ok else 3
                
                table_target = "dbo.corp_groups" if is_retail else "dbo.corp_groups"
                
                # Update MSSQL Status
                update_query = f"""
                    UPDATE {table_target} 
                    SET sync = %s 
                    WHERE corp_id = %s AND anniv = %s AND category = %s AND benefit = %s
                """
                mssql_cursor.execute(update_query, [
                    sync_status, 
                    val.get('corp_id'), 
                    val.get('anniv'), 
                    val.get('category_name'),
                    val.get('benefit_id')
                ])

                # Audit Logic (PostgreSQL)
                audit_fields = {
                    "corp_id": str(val.get('corp_id')),
                    "category": str(val.get('category_name')),
                    "anniv": str(val.get('anniv')),
                    "benefit_id": str(val.get('benefit_id')),
                    "benefit_name": str(val.get('benefit_name')),
                    "policy_no": str(val.get('policy_no')),
                    "request_object": smart_payload,
                    "smart_status": int(status_code),
                    "smart_response": res_data
                }

                if is_ok:
                    BenefitSyncSuccess.objects.create(**audit_fields)
                else:
                    BenefitSyncFailure.objects.create(**audit_fields)

            return is_ok
        except Exception as e:
            print(f"❌ Critical Audit/DB failure for Benefit {val.get('benefit_id')}: {e}")
            return False