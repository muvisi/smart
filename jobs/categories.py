
        
import requests
from urllib.parse import urlencode
from django.conf import settings
from engine.models import HaisCategorySyncSuccess, HaisCategorySyncFailure


class SyncHaisCategoriesService:

    def get_hais_token(self):
        payload = {
            "name": "generateToken",
            "param": {
                "consumer_key": settings.HAIS_API_CONSUMER_KEY,
                "consumer_secret": settings.HAIS_API_CONSUMER_SECRET
            }
        }

        resp = requests.post(
            settings.HAIS_API_BASE_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        data = resp.json()

        if data.get("response", {}).get("status") == 200:
            return data["response"]["result"]["accessToken"]

        return None

    def get_smart_token(self):
        payload = {
            "client_id": settings.SMART_CLIENT_ID,
            "client_secret": settings.SMART_CLIENT_SECRET,
            "grant_type": settings.SMART_GRANT_TYPE
        }

        resp = requests.post(
            f"{settings.SMART_ACCESS_TOKEN}{urlencode(payload)}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            verify=False
        )

        data = resp.json()
        return data.get("access_token")

    def get_hais_categories(self, hais_token):

        payload = {"name": "smartCategories", "param": {}}

        resp = requests.post(
            settings.HAIS_API_BASE_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {hais_token}",
                "Content-Type": "application/json"
            },
            timeout=30
        )

        return resp.json()

    def update_hais_category(self, hais_token, update_request):

        requests.post(
            settings.HAIS_API_BASE_URL,
            json=update_request,
            headers={
                "Authorization": f"Bearer {hais_token}",
                "Content-Type": "application/json"
            },
            timeout=30
        )

    def run(self):

        print("🔄 CATEGORY SYNC JOB STARTED")

        hais_token = self.get_hais_token()
        if not hais_token:
            print("❌ Failed to get HAIS token")
            return

        smart_token = self.get_smart_token()
        if not smart_token:
            print("❌ Failed to get SMART token")
            return

        categories_resp = self.get_hais_categories(hais_token)

        if categories_resp.get("response", {}).get("status") != 200:
            print("❌ Failed to fetch HAIS categories")
            return

        categories = categories_resp["response"]["result"]

        success = 0
        failed = 0

        for c in categories:

            cat_desc = c.get("category_name")
            anniv = c.get("anniv")

            cln_cat_code = f"{cat_desc}-{anniv}"
            cln_pol_code = c.get("corp_id")
            user_id = c.get("user_id")

            payload = {
                "catDesc": cln_cat_code,
                "clnPolCode": cln_pol_code,
                "userId": user_id,
                "clnCatCode": cln_cat_code,
                "country": settings.COUNTRY_CODE,
                "customerid": settings.SMART_CUSTOMER_ID
            }

            smart_url = f"{settings.SMART_API_BASE_URL}benefitCategories?{urlencode(payload)}"

            smart_resp = requests.post(
                smart_url,
                headers={"Authorization": f"Bearer {smart_token}"},
                verify=False
            )

            try:
                smart_data = smart_resp.json()
            except Exception:
                smart_data = {"error": "Invalid JSON response"}

            smart_httpcode = smart_resp.status_code

            sync_status = 2 if smart_data.get("successful") else 4

            request_object = {
                "url": smart_url,
                "payload": payload
            }

            update_req = {
                "name": "updateSchemeCategories",
                "param": {
                    "corp_id": cln_pol_code,
                    "anniv": anniv,
                    "category": cat_desc,
                    "status": sync_status
                }
            }

            self.update_hais_category(hais_token, update_req)

            if sync_status == 2:

                success += 1

                HaisCategorySyncSuccess.objects.create(
                    corp_id=cln_pol_code,
                    category_name=cat_desc,
                    request_object=request_object,
                    anniv=anniv,
                    user_id=user_id,
                    status_code=smart_httpcode,
                    smart_response=smart_data
                )

            else:

                failed += 1

                HaisCategorySyncFailure.objects.create(
                    corp_id=cln_pol_code,
                    category_name=cat_desc,
                    request_object=request_object,
                    anniv=anniv,
                    user_id=user_id,
                    status_code=smart_httpcode,
                    smart_response=smart_data
                )

        print(f"✅ CATEGORY SYNC DONE → {success} success, {failed} failed")




class SyncRetailCategoriesService:

    def get_hais_token(self):

        payload = {
            "name": "generateToken",
            "param": {
                "consumer_key": settings.HAIS_API_CONSUMER_KEY,
                "consumer_secret": settings.HAIS_API_CONSUMER_SECRET
            }
        }

        resp = requests.post(
            settings.HAIS_API_BASE_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        data = resp.json()

        if data.get("response", {}).get("status") == 200:
            return data["response"]["result"]["accessToken"]

        return None

    def get_smart_token(self):

        payload = {
            "client_id": settings.SMART_CLIENT_ID,
            "client_secret": settings.SMART_CLIENT_SECRET,
            "grant_type": settings.SMART_GRANT_TYPE
        }

        resp = requests.post(
            f"{settings.SMART_ACCESS_TOKEN}{urlencode(payload)}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            verify=False
        )

        data = resp.json()
        return data.get("access_token")

    def get_hais_categories(self, hais_token):

        payload = {"name": "smartRetailCategories", "param": {}}

        resp = requests.post(
            settings.HAIS_API_BASE_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {hais_token}",
                "Content-Type": "application/json"
            },
            timeout=30
        )

        return resp.json()

    def update_hais_category_status(self, hais_token, family_no, anniv, status):

        payload = {
            "name": "updateRetailSchemeCategory",
            "param": {
                "family_no": family_no,
                "anniv": anniv,
                "status": status
            }
        }

        requests.post(
            settings.HAIS_API_BASE_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {hais_token}",
                "Content-Type": "application/json"
            },
            timeout=30
        )

    def run(self):

        print("🔄 RETAIL CATEGORY SYNC JOB STARTED")

        hais_token = self.get_hais_token()
        if not hais_token:
            print("❌ Failed to get HAIS token")
            return

        smart_token = self.get_smart_token()
        if not smart_token:
            print("❌ Failed to get SMART token")
            return

        categories_resp = self.get_hais_categories(hais_token)

        if categories_resp.get("response", {}).get("status") != 200:
            print("❌ Failed to fetch retail categories")
            return

        categories = categories_resp["response"]["result"]

        success = 0
        failed = 0

        for c in categories:

            family_no = c.get("category_id")
            anniv = c.get("anniv")

            cat_desc = f"{c.get('category_name')}-{anniv}"
            cln_pol_code = c.get("scheme_id")
            user_id = c.get("user_id")

            payload = {
                "catDesc": cat_desc,
                "clnPolCode": cln_pol_code,
                "userId": user_id,
                "clnCatCode": cat_desc,
                "country": settings.COUNTRY_CODE,
                "customerid": settings.SMART_CUSTOMER_ID
            }

            smart_url = f"{settings.SMART_API_BASE_URL}benefitCategories?{urlencode(payload)}"

            smart_resp = requests.post(
                smart_url,
                headers={"Authorization": f"Bearer {smart_token}"},
                verify=False
            )

            try:
                smart_data = smart_resp.json()
            except Exception:
                smart_data = {"error": "Invalid JSON response"}

            smart_httpcode = smart_resp.status_code

            sync_status = 2 if smart_data.get("successful") else 4

            self.update_hais_category_status(hais_token, family_no, anniv, sync_status)

            if sync_status == 2:
                success += 1
            else:
                failed += 1

        print(f"✅ RETAIL CATEGORY SYNC DONE → {success} success, {failed} failed")