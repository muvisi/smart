
import json
from datetime import datetime
from urllib.parse import urlencode
import requests
from django.conf import settings
from django.db import connections
from engine.models import BenefitSyncSuccess, BenefitSyncFailure


class SyncHaisBenefitsService:
    """
    Sync corporate scheme benefits from external MSSQL (dbo.smart_categories) to SMART.
    Updates HAIS and logs API transactions.
    """

    country_code = "KE"

    def get_hais_token(self):
        """Get HAIS token using consumer key/secret"""
        payload = {
            "name": "generateToken",
            "param": {
                "consumer_key": settings.HAIS_API_CONSUMER_KEY,
                "consumer_secret": settings.HAIS_API_CONSUMER_SECRET
            }
        }
        try:
            resp = requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            data = resp.json()
            if data.get("response", {}).get("status") == 200:
                return data["response"]["result"]["accessToken"]
        except Exception as e:
            print("❌ Failed to get HAIS token:", e)
        return None

    def get_smart_token(self):
        """Get SMART token using client credentials"""
        payload = {
            "client_id": settings.SMART_CLIENT_ID,
            "client_secret": settings.SMART_CLIENT_SECRET,
            "grant_type": settings.SMART_GRANT_TYPE
        }
        try:
            resp = requests.post(
                settings.SMART_ACCESS_TOKEN,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                verify=False,
                timeout=30
            )
            resp.raise_for_status()
            token = resp.json().get("access_token")
            if not token:
                print("❌ SMART token not returned:", resp.text)
            return token
        except Exception as e:
            print("❌ Failed to get SMART token:", e)
            return None

    def get_benefits_from_db(self):
        """Fetch benefits from external MSSQL smart_categories table, JSON-safe"""
        benefits = []

        with connections['external_mssql'].cursor() as cursor:
            cursor.execute("SELECT DB_NAME()")
            print("Connected DB:", cursor.fetchone())

            cursor.execute("SELECT COUNT(*) FROM dbo.smart_bens_new")
            print("TOTAL ROWS:", cursor.fetchone())

            cursor.execute("SELECT * FROM dbo.smart_bens_new")
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

            print("RAW ROW COUNT:", len(rows))

            for row in rows:
                row_dict = dict(zip(columns, row))

                # ✅ JSON-safe
                for k, v in row_dict.items():
                    if isinstance(v, datetime):
                        row_dict[k] = v.isoformat()
                    elif v is None:
                        row_dict[k] = None
                    elif not isinstance(v, (int, float, bool)):
                        row_dict[k] = str(v)

                benefits.append(row_dict)

        print("FINAL BENEFITS SAMPLE:", benefits[:3])
        return benefits

    def update_hais_benefit(self, hais_token, clnPolCode, anniv, catDesc, clnBenCode, syncStatus):
        """Update HAIS benefit status"""
        payload = {
            "name": "updateSchemeBenefits",
            "param": {
                "corp_id": clnPolCode,
                "anniv": anniv,
                "category": catDesc,
                "benefit": clnBenCode,
                "status": syncStatus
            }
        }
        try:
            requests.post(
                settings.HAIS_API_BASE_URL,
                headers={"Authorization": f"Bearer {hais_token}", "Content-Type": "application/json"},
                json=payload,
                timeout=30
            )
        except Exception as e:
            print(f"❌ Failed to update HAIS benefit {clnBenCode}:", e)

    def create_hais_log(self, hais_token, smart_httpcode, request_obj, response_obj):
        """Log API call to HAIS"""
        payload = {
            "name": "createApiLog",
            "param": {
                "source": "HAIS-SMART",
                "transactionName": "Corporate Scheme Benefit",
                "statusCode": smart_httpcode,
                "requestObject": [json.dumps(request_obj)],
                "responseObject": [json.dumps(response_obj)]
            }
        }
        try:
            requests.post(
                settings.HAIS_API_BASE_URL,
                headers={"Authorization": f"Bearer {hais_token}", "Content-Type": "application/json"},
                json=payload,
                timeout=30
            )
        except Exception as e:
            print("❌ Failed to log API to HAIS:", e)

    def run(self):
        """Run the benefits sync"""
        hais_token = self.get_hais_token()
        if not hais_token:
            print("❌ HAIS token not valid")
            return

        smart_token = self.get_smart_token()
        if not smart_token:
            print("❌ SMART token not received")
            return

        benefits_list = self.get_benefits_from_db()
        if not benefits_list:
            print("❌ No benefits found in DB")
            return

        success, failed = 0, 0

        for b in benefits_list:
            try:
                benefitDesc = b.get("benefit_name")
                policyNumber = b.get("policy_no")
                benTypeId = b.get("benefit_sharing")
                subLimitAmt = b.get("limit")
                serviceType = b.get("benefit_class")
                memAssignedBenefit = b.get("member_assigned_benefit")
                clnPolCode = b.get("corp_id")
                catDesc = b.get("category_name")
                anniv = b.get("anniv")
                catCode = f"{catDesc}-{anniv}"
                clnBenCode = b.get("benefit_id")
                benTypDesc = b.get("benefit_sharing_descr")
                userId = b.get("user_id")
                benLinked2Tqcode = "-" if b.get("sub_limit_of") == "0" else b.get("sub_limit_of")

                smart_payload = {
                    "benefitDesc": benefitDesc,
                    "policyNumber": policyNumber,
                    "benTypeId": benTypeId,
                    "subLimitAmt": subLimitAmt,
                    "serviceType": serviceType,
                    "memAssignedBenefit": memAssignedBenefit,
                    "clnPolCode": clnPolCode,
                    "catCode": catCode,
                    "clnBenCode": clnBenCode,
                    "benTypDesc": benTypDesc,
                    "benLinked2Tqcode": benLinked2Tqcode,
                    "userId": userId,
                    "countrycode": self.country_code,
                    "customerid": settings.SMART_CUSTOMER_ID
                }

                smart_endpoint = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(smart_payload)}"
                try:
                    smart_resp = requests.post(
                        smart_endpoint,
                        headers={"Authorization": f"Bearer {smart_token}"},
                        verify=False,
                        timeout=30
                    )
                    smart_httpcode = smart_resp.status_code
                    decodedSmartBenefitResponse = smart_resp.json()
                    syncStatus = 1 if decodedSmartBenefitResponse.get("successful") else 3
                except Exception as e:
                    smart_httpcode = 0
                    syncStatus = 3
                    decodedSmartBenefitResponse = {"error": str(e)}

                # ✅ Update HAIS and log exactly as before
                self.update_hais_benefit(hais_token, clnPolCode, anniv, catDesc, clnBenCode, syncStatus)
                self.create_hais_log(hais_token, smart_httpcode, b, decodedSmartBenefitResponse)

                # Save in DB
                summary = {
                    "corp_id": clnPolCode,
                    "category": catDesc,
                    "anniv": anniv,
                    "benefit_id": clnBenCode,
                    "benefit_name": benefitDesc,
                    "policy_no": policyNumber,
                    "smart_status": smart_httpcode,
                    "smart_response": decodedSmartBenefitResponse
                }

                if syncStatus == 1:
                    success += 1
                    BenefitSyncSuccess.objects.create(**summary)
                else:
                    failed += 1
                    BenefitSyncFailure.objects.create(**summary)

            except Exception as e:
                failed += 1
                BenefitSyncFailure.objects.create(
                    corp_id=b.get("corp_id"),
                    category=b.get("category_name"),
                    anniv=b.get("anniv"),
                    benefit_id=b.get("benefit_id"),
                    benefit_name=b.get("benefit_name"),
                    policy_no=b.get("policy_no"),
                    smart_status=500,
                    smart_response={"error": str(e)}
                )

        print(f"✅ {success} benefit(s) successfully synced to SMART and updated HAIS. {failed} failed.")

# # engine/benefits/services.py
# import time
# from urllib.parse import urlencode
# import requests
# from django.conf import settings
# from engine.models import BenefitSyncSuccess, BenefitSyncFailure

# class SyncHaisRetailBenefitsService:
#     """
#     Service to sync HAIS retail benefits to SMART using consumer key/secret for token,
#     with logging and DB updates.
#     """

#     country_code = "KE"

#     def get_hais_token(self):
#         """Get HAIS token via generateToken endpoint using consumer key/secret"""
#         payload = {
#             "name": "generateToken",
#             "param": {
#                 "consumer_key": settings.HAIS_API_CONSUMER_KEY,
#                 "consumer_secret": settings.HAIS_API_CONSUMER_SECRET
#             }
#         }
#         try:
#             resp = requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={"Content-Type": "application/json"},
#                 timeout=30
#             )
#             data = resp.json()
#             if data.get("response", {}).get("status") == 200:
#                 return data["response"]["result"]["accessToken"]
#         except Exception:
#             pass
#         return None

#     def get_smart_token(self):
#         """Get SMART token"""
#         payload = {
#             "client_id": settings.SMART_CLIENT_ID,
#             "client_secret": settings.SMART_CLIENT_SECRET,
#             "grant_type": settings.SMART_GRANT_TYPE
#         }
#         token_url = f"{settings.SMART_ACCESS_TOKEN}?{urlencode(payload)}"
#         try:
#             resp = requests.post(
#                 token_url,
#                 headers={"Content-Type": "application/x-www-form-urlencoded"},
#                 verify=False,
#                 timeout=30
#             )
#             return resp.json().get("access_token")
#         except Exception:
#             return None

#     def get_hais_benefits(self, hais_token):
#         """Fetch HAIS retail benefits"""
#         payload = {"name": "smartRetailBenefits", "param": {}}
#         try:
#             resp = requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )
#             return resp.json()
#         except Exception as e:
#             return {"error": str(e)}

#     def update_hais_benefit_status(self, hais_token, family_no, anniv, cln_ben_code, status):
#         """Update HAIS retail benefit status"""
#         payload = {
#             "name": "updateRetailSchemeBenefits",
#             "param": {
#                 "family_no": family_no,
#                 "anniv": anniv,
#                 "benefit": cln_ben_code,
#                 "status": status
#             }
#         }
#         try:
#             requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )
#         except Exception:
#             pass

#     def create_hais_log(self, hais_token, smart_httpcode, request_obj, response_obj):
#         """Log retail benefit sync to HAIS"""
#         payload = {
#             "name": "createApiLog",
#             "param": {
#                 "source": "HAIS-SMART",
#                 "transactionName": "Retail Scheme Benefit",
#                 "statusCode": smart_httpcode,
#                 "requestObject": [request_obj],
#                 "responseObject": [response_obj]
#             }
#         }
#         try:
#             requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )
#         except Exception:
#             pass

#     def run(self):
#         hais_token = self.get_hais_token()
#         if not hais_token:
#             print("Failed to get HAIS token")
#             return

#         smart_token = self.get_smart_token()
#         if not smart_token:
#             print("Failed to get SMART token")
#             return

#         benefits_resp = self.get_hais_benefits(hais_token)
#         if benefits_resp.get("response", {}).get("status") != 200:
#             print("Failed to fetch HAIS benefits")
#             return

#         benefits = benefits_resp["response"]["result"]
#         print(f"Fetched {len(benefits)} HAIS retail benefits")

#         success, failed = 0, 0
#         max_per_minute = 200
#         delay_per_request = 60 / max_per_minute

#         for idx, b in enumerate(benefits, start=1):
#             try:
#                 family_no = b.get("category_id")
#                 benefit_desc = b.get("benefit_name")
#                 policy_number = b.get("scheme_id")
#                 ben_type_id = b.get("benefit_sharing")
#                 sub_limit_amt = b.get("limit")
#                 service_type = b.get("service_type")
#                 mem_assigned_benefit = b.get("member_assigned_benefit")
#                 cln_pol_code = b.get("scheme_id")
#                 cat_code = f"{b.get('category_name')}-{b.get('anniv')}"
#                 cln_ben_code = b.get("benefit_id")
#                 ben_typ_desc = b.get("benefit_sharing_descr")
#                 anniv = b.get("anniv")
#                 user_id = b.get("user_id")
#                 ben_linked2tqcode = b.get("sub_limit_of") if b.get("sub_limit_of") != "0" else "-"

#                 smart_payload = {
#                     "benefitDesc": benefit_desc,
#                     "policyNumber": policy_number,
#                     "benTypeId": ben_type_id,
#                     "subLimitAmt": sub_limit_amt,
#                     "serviceType": service_type,
#                     "memAssignedBenefit": mem_assigned_benefit,
#                     "clnPolCode": cln_pol_code,
#                     "catCode": cat_code,
#                     "clnBenCode": cln_ben_code,
#                     "benTypDesc": ben_typ_desc,
#                     "benLinked2Tqcode": ben_linked2tqcode,
#                     "userId": user_id,
#                     "countrycode": self.country_code,
#                     "customerid": settings.SMART_CUSTOMER_ID
#                 }

#                 smart_url = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(smart_payload)}"
#                 try:
#                     smart_resp = requests.post(
#                         smart_url,
#                         headers={"Authorization": f"Bearer {smart_token}"},
#                         verify=False,
#                         timeout=30
#                     )
#                     smart_data = smart_resp.json()
#                     smart_httpcode = smart_resp.status_code
#                 except Exception:
#                     smart_data = {}
#                     smart_httpcode = 500

#                 sync_status = 1 if smart_data.get("successful") else 3

#                 self.update_hais_benefit_status(hais_token, family_no, anniv, cln_ben_code, sync_status)
#                 self.create_hais_log(hais_token, smart_httpcode, b, smart_data)

#                 benefit_summary = {
#                     "benefit_id": cln_ben_code,
#                     "benefit_name": benefit_desc,
#                     "policy_no": policy_number,
#                     "corp_id": cln_pol_code,
#                     "category": b.get("category_name"),
#                     "anniv": anniv,
#                     "smart_status": smart_httpcode,
#                     "smart_response": smart_data
#                 }

#                 if sync_status == 1:
#                     BenefitSyncSuccess.objects.create(**benefit_summary)
#                     success += 1
#                 else:
#                     BenefitSyncFailure.objects.create(**benefit_summary)
#                     failed += 1

#                 print(f"Pushed benefit {idx}: {benefit_summary}")

#                 # Throttle requests
#                 if idx % max_per_minute == 0:
#                     time.sleep(60)
#                 else:
#                     time.sleep(delay_per_request)

#             except Exception as e:
#                 failed += 1
#                 BenefitSyncFailure.objects.create(
#                     corp_id=b.get("scheme_id"),
#                     category=b.get("category_name"),
#                     anniv=b.get("anniv"),
#                     benefit_id=b.get("benefit_id"),
#                     benefit_name=b.get("benefit_name"),
#                     policy_no=b.get("scheme_id"),
#                     smart_status=500,
#                     smart_response={"error": str(e)}
#                 )

#         print(f"Sync complete: {success} succeeded, {failed} failed")

# engine/benefits/services.py

# import time
# from urllib.parse import urlencode
# import requests
# from django.conf import settings
# from engine.models import BenefitSyncSuccess, BenefitSyncFailure


# class SyncHaisRetailBenefitsService:

#     country_code = "KE"

#     def get_hais_token(self):
#         payload = {
#             "name": "generateToken",
#             "param": {
#                 "consumer_key": settings.HAIS_API_CONSUMER_KEY,
#                 "consumer_secret": settings.HAIS_API_CONSUMER_SECRET
#             }
#         }

#         try:
#             resp = requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={"Content-Type": "application/json"},
#                 timeout=30
#             )
#             data = resp.json()

#             if data.get("response", {}).get("status") == 200:
#                 return data["response"]["result"]["accessToken"]

#         except Exception:
#             pass

#         return None


#     def get_smart_token(self):
#         payload = {
#             "client_id": settings.SMART_CLIENT_ID,
#             "client_secret": settings.SMART_CLIENT_SECRET,
#             "grant_type": settings.SMART_GRANT_TYPE
#         }

#         token_url = f"{settings.SMART_ACCESS_TOKEN}?{urlencode(payload)}"

#         try:
#             resp = requests.post(
#                 token_url,
#                 headers={"Content-Type": "application/x-www-form-urlencoded"},
#                 verify=False,
#                 timeout=30
#             )

#             return resp.json().get("access_token")

#         except Exception:
#             return None


#     def get_hais_benefits(self, hais_token):
#         payload = {"name": "smartRetailBenefits", "param": {}}

#         try:
#             resp = requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )

#             return resp.json()

#         except Exception as e:
#             return {"error": str(e)}


#     def update_hais_benefit_status(self, hais_token, family_no, anniv, cln_ben_code, status):

#         payload = {
#             "name": "updateRetailSchemeBenefits",
#             "param": {
#                 "family_no": family_no,
#                 "anniv": anniv,
#                 "benefit": cln_ben_code,
#                 "status": status
#             }
#         }

#         try:
#             requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )
#         except Exception:
#             pass


#     def create_hais_log(self, hais_token, smart_httpcode, request_obj, response_obj):

#         payload = {
#             "name": "createApiLog",
#             "param": {
#                 "source": "HAIS-SMART",
#                 "transactionName": "Retail Scheme Benefit",
#                 "statusCode": smart_httpcode,
#                 "requestObject": [request_obj],
#                 "responseObject": [response_obj]
#             }
#         }

#         try:
#             requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )
#         except Exception:
#             pass


#     def run(self):

#         hais_token = self.get_hais_token()
#         if not hais_token:
#             print("Failed to get HAIS token")
#             return

#         smart_token = self.get_smart_token()
#         if not smart_token:
#             print("Failed to get SMART token")
#             return

#         benefits_resp = self.get_hais_benefits(hais_token)

#         if benefits_resp.get("response", {}).get("status") != 200:
#             print("Failed to fetch HAIS benefits")
#             return

#         benefits = benefits_resp["response"]["result"]

#         print(f"Fetched {len(benefits)} HAIS retail benefits")

#         success = 0
#         failed = 0

#         max_per_minute = 200
#         delay_per_request = 60 / max_per_minute


#         for idx, b in enumerate(benefits, start=1):

#             try:

#                 family_no = b.get("category_id")
#                 benefit_desc = b.get("benefit_name")
#                 policy_number = b.get("scheme_id")
#                 ben_type_id = b.get("benefit_sharing")
#                 sub_limit_amt = b.get("limit")
#                 service_type = b.get("service_type")
#                 mem_assigned_benefit = b.get("member_assigned_benefit")
#                 cln_pol_code = b.get("scheme_id")
#                 cat_code = f"{b.get('category_name')}-{b.get('anniv')}"
#                 cln_ben_code = b.get("benefit_id")
#                 ben_typ_desc = b.get("benefit_sharing_descr")
#                 anniv = b.get("anniv")
#                 user_id = b.get("user_id")

#                 ben_linked2tqcode = b.get("sub_limit_of") if b.get("sub_limit_of") != "0" else "-"


#                 smart_payload = {
#                     "benefitDesc": benefit_desc,
#                     "policyNumber": policy_number,
#                     "benTypeId": ben_type_id,
#                     "subLimitAmt": sub_limit_amt,
#                     "serviceType": service_type,
#                     "memAssignedBenefit": mem_assigned_benefit,
#                     "clnPolCode": cln_pol_code,
#                     "catCode": cat_code,
#                     "clnBenCode": cln_ben_code,
#                     "benTypDesc": ben_typ_desc,
#                     "benLinked2Tqcode": ben_linked2tqcode,
#                     "userId": user_id,
#                     "countrycode": self.country_code,
#                     "customerid": settings.SMART_CUSTOMER_ID
#                 }

#                 print("SMART BENEFIT PAYLOAD:", smart_payload)

#                 smart_url = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(smart_payload)}"

#                 try:

#                     smart_resp = requests.post(
#                         smart_url,
#                         headers={"Authorization": f"Bearer {smart_token}"},
#                         verify=False,
#                         timeout=30
#                     )

#                     smart_data = smart_resp.json()
#                     smart_httpcode = smart_resp.status_code

#                 except Exception:

#                     smart_data = {}
#                     smart_httpcode = 500


#                 sync_status = 1 if smart_data.get("successful") else 3


#                 self.update_hais_benefit_status(
#                     hais_token,
#                     family_no,
#                     anniv,
#                     cln_ben_code,
#                     sync_status
#                 )


#                 self.create_hais_log(
#                     hais_token,
#                     smart_httpcode,
#                     smart_payload,
#                     smart_data
#                 )


#                 benefit_summary = {
#                     "corp_id": cln_pol_code,
#                     "category": b.get("category_name"),
#                     "anniv": anniv,
#                     "benefit_id": cln_ben_code,
#                     "benefit_name": benefit_desc,
#                     "policy_no": policy_number,
#                     "request_object": smart_payload,
#                     "smart_status": smart_httpcode,
#                     "smart_response": smart_data
#                 }


#                 if sync_status == 1:
#                     BenefitSyncSuccess.objects.create(**benefit_summary)
#                     success += 1
#                 else:
#                     BenefitSyncFailure.objects.create(**benefit_summary)
#                     failed += 1


#                 print(f"Pushed benefit {idx}: {benefit_summary}")


#                 if idx % max_per_minute == 0:
#                     time.sleep(60)
#                 else:
#                     time.sleep(delay_per_request)


#             except Exception as e:

#                 failed += 1

#                 BenefitSyncFailure.objects.create(
#                     corp_id=b.get("scheme_id"),
#                     category=b.get("category_name"),
#                     anniv=b.get("anniv"),
#                     benefit_id=b.get("benefit_id"),
#                     benefit_name=b.get("benefit_name"),
#                     policy_no=b.get("scheme_id"),
#                     request_object=b,
#                     smart_status=500,
#                     smart_response={"error": str(e)}
#                 )


#         print(f"Sync complete: {success} succeeded, {failed} failed")


# import time
# import json
# from urllib.parse import urlencode
# import requests
# from django.conf import settings
# from engine.models import BenefitSyncSuccess, BenefitSyncFailure


# class SyncHaisRetailBenefitsService:
#     """
#     Sync HAIS retail scheme benefits to SMART.
#     Updated with working token logic and improved logging.
#     """

#     country_code = "KE"

#     def get_hais_token(self):
#         """Get HAIS token using consumer key/secret"""
#         payload = {
#             "name": "generateToken",
#             "param": {
#                 "consumer_key": settings.HAIS_API_CONSUMER_KEY,
#                 "consumer_secret": settings.HAIS_API_CONSUMER_SECRET
#             }
#         }
#         try:
#             resp = requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={"Content-Type": "application/json"},
#                 timeout=30
#             )
#             data = resp.json()
#             if data.get("response", {}).get("status") == 200:
#                 return data["response"]["result"]["accessToken"]
#         except Exception as e:
#             print("❌ Failed to get HAIS token:", e)
#         return None

#     def get_smart_token(self):
#         """Get SMART token using client credentials (Form-encoded POST)"""
#         payload = {
#             "client_id": settings.SMART_CLIENT_ID,
#             "client_secret": settings.SMART_CLIENT_SECRET,
#             "grant_type": settings.SMART_GRANT_TYPE
#         }
#         try:
#             # Changed from query params in URL to data=payload (form-encoded body)
#             resp = requests.post(
#                 settings.SMART_ACCESS_TOKEN,
#                 data=payload,
#                 headers={"Content-Type": "application/x-www-form-urlencoded"},
#                 verify=False,
#                 timeout=30
#             )
#             resp.raise_for_status()
#             token = resp.json().get("access_token")
#             if not token:
#                 print("❌ SMART token not returned:", resp.text)
#             return token
#         except Exception as e:
#             print("❌ Failed to get SMART token:", e)
#             return None

#     def get_hais_benefits(self, hais_token):
#         """Fetch retail benefits from HAIS"""
#         payload = {"name": "smartRetailBenefits", "param": {}}
#         try:
#             resp = requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )
#             return resp.json()
#         except Exception as e:
#             print("❌ Failed to fetch HAIS benefits:", e)
#             return {"response": {"status": 500, "result": None, "error": str(e)}}

#     def update_hais_benefit_status(self, hais_token, family_no, anniv, cln_ben_code, status):
#         """Update HAIS retail benefit status"""
#         payload = {
#             "name": "updateRetailSchemeBenefits",
#             "param": {
#                 "family_no": family_no,
#                 "anniv": anniv,
#                 "benefit": cln_ben_code,
#                 "status": status
#             }
#         }
#         try:
#             requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )
#         except Exception as e:
#             print(f"❌ Failed to update HAIS status for {cln_ben_code}:", e)

#     def create_hais_log(self, hais_token, smart_httpcode, request_obj, response_obj):
#         """Log API call to HAIS using serialized JSON"""
#         payload = {
#             "name": "createApiLog",
#             "param": {
#                 "source": "HAIS-SMART",
#                 "transactionName": "Retail Scheme Benefit",
#                 "statusCode": smart_httpcode,
#                 "requestObject": [json.dumps(request_obj)],
#                 "responseObject": [json.dumps(response_obj)]
#             }
#         }
#         try:
#             requests.post(
#                 settings.HAIS_API_BASE_URL,
#                 json=payload,
#                 headers={
#                     "Authorization": f"Bearer {hais_token}",
#                     "Content-Type": "application/json"
#                 },
#                 timeout=30
#             )
#         except Exception as e:
#             print("❌ Failed to log API to HAIS:", e)

#     def run(self):
#         """Run the retail benefits sync"""
#         hais_token = self.get_hais_token()
#         if not hais_token:
#             print("❌ HAIS token not valid")
#             return

#         smart_token = self.get_smart_token()
#         if not smart_token:
#             print("❌ SMART token not received")
#             return

#         benefits_resp = self.get_hais_benefits(hais_token)
#         if benefits_resp.get("response", {}).get("status") != 200:
#             print("❌ HAIS benefits fetch failed")
#             return

#         benefits = benefits_resp["response"]["result"]
#         print(f"Fetched {len(benefits)} HAIS retail benefits")

#         success, failed = 0, 0
#         max_per_minute = 200
#         delay_per_request = 60 / max_per_minute

#         for idx, b in enumerate(benefits, start=1):
#             try:
#                 family_no = b.get("category_id")
#                 benefit_desc = b.get("benefit_name")
#                 policy_number = b.get("scheme_id")
#                 ben_type_id = b.get("benefit_sharing")
#                 sub_limit_amt = b.get("limit")
#                 service_type = b.get("service_type")
#                 mem_assigned_benefit = b.get("member_assigned_benefit")
#                 cln_pol_code = b.get("scheme_id")
#                 cat_code = f"{b.get('category_name')}-{b.get('anniv')}"
#                 cln_ben_code = b.get("benefit_id")
#                 ben_typ_desc = b.get("benefit_sharing_descr")
#                 anniv = b.get("anniv")
#                 user_id = b.get("user_id")
#                 ben_linked2tqcode = b.get("sub_limit_of") if b.get("sub_limit_of") != "0" else "-"

#                 smart_payload = {
#                     "benefitDesc": benefit_desc,
#                     "policyNumber": policy_number,
#                     "benTypeId": ben_type_id,
#                     "subLimitAmt": sub_limit_amt,
#                     "serviceType": service_type,
#                     "memAssignedBenefit": mem_assigned_benefit,
#                     "clnPolCode": cln_pol_code,
#                     "catCode": cat_code,
#                     "clnBenCode": cln_ben_code,
#                     "benTypDesc": ben_typ_desc,
#                     "benLinked2Tqcode": ben_linked2tqcode,
#                     "userId": user_id,
#                     "countrycode": self.country_code,
#                     "customerid": settings.SMART_CUSTOMER_ID
#                 }

#                 smart_url = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(smart_payload)}"

#                 try:
#                     smart_resp = requests.post(
#                         smart_url,
#                         headers={"Authorization": f"Bearer {smart_token}"},
#                         verify=False,
#                         timeout=30
#                     )
#                     smart_data = smart_resp.json()
#                     smart_httpcode = smart_resp.status_code
#                     sync_status = 1 if smart_data.get("successful") else 3
#                 except Exception as e:
#                     smart_data = {"error": str(e)}
#                     smart_httpcode = 500
#                     sync_status = 3

#                 # Update HAIS & Create Log
#                 self.update_hais_benefit_status(hais_token, family_no, anniv, cln_ben_code, sync_status)
#                 self.create_hais_log(hais_token, smart_httpcode, smart_payload, smart_data)

#                 benefit_summary = {
#                     "corp_id": cln_pol_code,
#                     "category": b.get("category_name"),
#                     "anniv": anniv,
#                     "benefit_id": cln_ben_code,
#                     "benefit_name": benefit_desc,
#                     "policy_no": policy_number,
#                     "smart_status": smart_httpcode,
#                     "smart_response": smart_data
#                 }

#                 if sync_status == 1:
#                     BenefitSyncSuccess.objects.create(**benefit_summary)
#                     success += 1
#                 else:
#                     BenefitSyncFailure.objects.create(**benefit_summary)
#                     failed += 1

#                 print(f"Pushed benefit {idx}/{len(benefits)}: {cln_ben_code}")

#                 # Throttling
#                 # if idx % max_per_minute == 0:
#                 #     time.sleep(60)
#                 # else:
#                 #     time.sleep(delay_per_request)

#             except Exception as e:
#                 failed += 1
#                 print(f"❌ Error processing benefit index {idx}: {e}")
#                 BenefitSyncFailure.objects.create(
#                     corp_id=b.get("scheme_id"),
#                     category=b.get("category_name"),
#                     anniv=b.get("anniv"),
#                     benefit_id=b.get("benefit_id"),
#                     benefit_name=b.get("benefit_name"),
#                     policy_no=b.get("scheme_id"),
#                     smart_status=500,
#                     smart_response={"error": str(e)}
#                 )

#         print(f"Sync complete: {success} succeeded, {failed} failed")


import time
import json
from datetime import datetime
from urllib.parse import urlencode
import requests
from django.conf import settings
from django.db import connections
from engine.models import BenefitSyncSuccess, BenefitSyncFailure


class SyncHaisRetailBenefitsService:
    """
    Sync retail scheme benefits from external MSSQL (dbo.smart_categories) to SMART.
    Updates HAIS and logs API transactions.
    """

    country_code = "KE"

    def get_hais_token(self):
        """Get HAIS token using consumer key/secret"""
        payload = {
            "name": "generateToken",
            "param": {
                "consumer_key": settings.HAIS_API_CONSUMER_KEY,
                "consumer_secret": settings.HAIS_API_CONSUMER_SECRET
            }
        }
        try:
            resp = requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            data = resp.json()
            if data.get("response", {}).get("status") == 200:
                return data["response"]["result"]["accessToken"]
        except Exception as e:
            print("❌ Failed to get HAIS token:", e)
        return None

    def get_smart_token(self):
        """Get SMART token using client credentials (Form-encoded POST)"""
        payload = {
            "client_id": settings.SMART_CLIENT_ID,
            "client_secret": settings.SMART_CLIENT_SECRET,
            "grant_type": settings.SMART_GRANT_TYPE
        }
        try:
            resp = requests.post(
                settings.SMART_ACCESS_TOKEN,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                verify=False,
                timeout=30
            )
            resp.raise_for_status()
            token = resp.json().get("access_token")
            if not token:
                print("❌ SMART token not returned:", resp.text)
            return token
        except Exception as e:
            print("❌ Failed to get SMART token:", e)
            return None

    def get_retail_benefits_from_db(self):
        """Fetch retail benefits from external MSSQL smart_categories table"""
        benefits = []

        with connections['external_mssql'].cursor() as cursor:
            cursor.execute("SELECT DB_NAME()")
            print("Connected DB:", cursor.fetchone())

            cursor.execute("SELECT COUNT(*) FROM dbo.smart_retail_categories_new")
            print("TOTAL ROWS:", cursor.fetchone())

            cursor.execute("SELECT * FROM dbo.smart_retail_categories_new")
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

            print("RAW ROW COUNT:", len(rows))

            for row in rows:
                row_dict = dict(zip(columns, row))

                # Make JSON-safe
                for k, v in row_dict.items():
                    if isinstance(v, datetime):
                        row_dict[k] = v.isoformat()
                    elif v is None:
                        row_dict[k] = None
                    elif not isinstance(v, (int, float, bool)):
                        row_dict[k] = str(v)

                benefits.append(row_dict)

        print("FINAL BENEFITS SAMPLE:", benefits[:3])
        return benefits

    def update_hais_benefit_status(self, hais_token, family_no, anniv, cln_ben_code, status):
        """Update HAIS retail benefit status"""
        payload = {
            "name": "updateRetailSchemeBenefits",
            "param": {
                "family_no": family_no,
                "anniv": anniv,
                "benefit": cln_ben_code,
                "status": status
            }
        }
        try:
            requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {hais_token}",
                    "Content-Type": "application/json"
                },
                timeout=30
            )
        except Exception as e:
            print(f"❌ Failed to update HAIS status for {cln_ben_code}:", e)

    def create_hais_log(self, hais_token, smart_httpcode, request_obj, response_obj):
        """Log API call to HAIS using serialized JSON"""
        payload = {
            "name": "createApiLog",
            "param": {
                "source": "HAIS-SMART",
                "transactionName": "Retail Scheme Benefit",
                "statusCode": smart_httpcode,
                "requestObject": [json.dumps(request_obj)],
                "responseObject": [json.dumps(response_obj)]
            }
        }
        try:
            requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {hais_token}",
                    "Content-Type": "application/json"
                },
                timeout=30
            )
        except Exception as e:
            print("❌ Failed to log API to HAIS:", e)

    def run(self):
        """Run the retail benefits sync"""
        hais_token = self.get_hais_token()
        if not hais_token:
            print("❌ HAIS token not valid")
            return

        smart_token = self.get_smart_token()
        if not smart_token:
            print("❌ SMART token not received")
            return

        benefits = self.get_retail_benefits_from_db()
        if not benefits:
            print("❌ No benefits found in DB")
            return

        print(f"Fetched {len(benefits)} retail benefits from DB")

        success, failed = 0, 0

        for idx, b in enumerate(benefits, start=1):
            try:
                family_no = b.get("category_id")
                benefit_desc = b.get("benefit_name")
                policy_number = b.get("scheme_id")
                ben_type_id = b.get("benefit_sharing")
                sub_limit_amt = b.get("limit")
                service_type = b.get("service_type")
                mem_assigned_benefit = b.get("member_assigned_benefit")
                cln_pol_code = b.get("scheme_id")
                cat_code = f"{b.get('category_name')}-{b.get('anniv')}"
                cln_ben_code = b.get("benefit_id")
                ben_typ_desc = b.get("benefit_sharing_descr")
                anniv = b.get("anniv")
                user_id = b.get("user_id")
                ben_linked2tqcode = b.get("sub_limit_of") if b.get("sub_limit_of") != "0" else "-"

                smart_payload = {
                    "benefitDesc": benefit_desc,
                    "policyNumber": policy_number,
                    "benTypeId": ben_type_id,
                    "subLimitAmt": sub_limit_amt,
                    "serviceType": service_type,
                    "memAssignedBenefit": mem_assigned_benefit,
                    "clnPolCode": cln_pol_code,
                    "catCode": cat_code,
                    "clnBenCode": cln_ben_code,
                    "benTypDesc": ben_typ_desc,
                    "benLinked2Tqcode": ben_linked2tqcode,
                    "userId": user_id,
                    "countrycode": self.country_code,
                    "customerid": settings.SMART_CUSTOMER_ID
                }

                smart_url = f"{settings.SMART_API_BASE_URL}benefits?{urlencode(smart_payload)}"

                try:
                    smart_resp = requests.post(
                        smart_url,
                        headers={"Authorization": f"Bearer {smart_token}"},
                        verify=False,
                        timeout=30
                    )
                    smart_data = smart_resp.json()
                    smart_httpcode = smart_resp.status_code
                    sync_status = 1 if smart_data.get("successful") else 3
                except Exception as e:
                    smart_data = {"error": str(e)}
                    smart_httpcode = 500
                    sync_status = 3

                # ✅ Update HAIS & Create Log exactly as before
                self.update_hais_benefit_status(hais_token, family_no, anniv, cln_ben_code, sync_status)
                self.create_hais_log(hais_token, smart_httpcode, smart_payload, smart_data)

                benefit_summary = {
                    "corp_id": cln_pol_code,
                    "category": b.get("category_name"),
                    "anniv": anniv,
                    "benefit_id": cln_ben_code,
                    "benefit_name": benefit_desc,
                    "policy_no": policy_number,
                    "smart_status": smart_httpcode,
                    "smart_response": smart_data
                }

                if sync_status == 1:
                    BenefitSyncSuccess.objects.create(**benefit_summary)
                    success += 1
                else:
                    BenefitSyncFailure.objects.create(**benefit_summary)
                    failed += 1

                print(f"Pushed benefit {idx}/{len(benefits)}: {cln_ben_code}")

            except Exception as e:
                failed += 1
                print(f"❌ Error processing benefit index {idx}: {e}")
                BenefitSyncFailure.objects.create(
                    corp_id=b.get("scheme_id"),
                    category=b.get("category_name"),
                    anniv=b.get("anniv"),
                    benefit_id=b.get("benefit_id"),
                    benefit_name=b.get("benefit_name"),
                    policy_no=b.get("scheme_id"),
                    smart_status=500,
                    smart_response={"error": str(e)}
                )

        print(f"✅ Retail sync complete: {success} succeeded, {failed} failed")