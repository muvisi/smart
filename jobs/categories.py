
import json
from datetime import datetime
from urllib.parse import urlencode
import requests
from django.conf import settings
from django.db import connections


class SyncHaisCategoriesService:

    def get_hais_token(self):
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
            resp.raise_for_status()  # raises HTTPError for 4xx/5xx

            try:
                data = resp.json()
            except ValueError:  # JSON decode failed
                print(f"Invalid JSON response: {resp.text}")
                return None

            if data.get("response", {}).get("status") == 200:
                return data["response"]["result"]["accessToken"]
            else:
                print(f"Failed to get token: {data}")
                return None

        except requests.RequestException as e:
            print(f"HTTP request failed: {e}")
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

    def get_categories_from_db(self):
        """Fetch categories from smart_categories table via external_mssql, JSON-safe"""
        categories = []

        with connections['external_mssql'].cursor() as cursor:
            # ✅ CHECK DB CONNECTION
            cursor.execute("SELECT DB_NAME()")
            print("Connected DB:", cursor.fetchone())

            # ✅ DEBUG COUNT
            cursor.execute("SELECT COUNT(*) FROM dbo.smart_categories where synced is null")
            print("TOTAL ROWS:", cursor.fetchone())

            # ✅ FETCH DATA
            cursor.execute("SELECT * FROM dbo.smart_categories where synced is null")
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

            print("RAW ROW COUNT:", len(rows))

            for row in rows:
                row_dict = dict(zip(columns, row))

                # ✅ MAKE JSON SAFE
                for k, v in row_dict.items():
                    if isinstance(v, datetime):
                        row_dict[k] = v.isoformat()
                    elif v is None:
                        row_dict[k] = None
                    elif not isinstance(v, (int, float, bool)):
                        row_dict[k] = str(v)

                categories.append(row_dict)

        print("FINAL CATEGORIES SAMPLE:", categories[:3])
        return categories

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

        categories = self.get_categories_from_db()
        if not categories:
            print("❌ No categories found in DB")
            return

        success = 0
        failed = 0

        for c in categories:
            family_no = c.get("corp_id") or c.get("category_id")
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

            sync_status = 2 if smart_data.get("successful") else 4
            self.update_hais_category_status(hais_token, family_no, anniv, sync_status)

            if sync_status == 2:
                success += 1
            else:
                failed += 1

        print(f"✅ RETAIL CATEGORY SYNC DONE → {success} success, {failed} failed")
        
        
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

    def get_categories_from_db(self):
        """Fetch categories from smart_categories table via external_mssql, JSON-safe"""
        categories = []

        with connections['external_mssql'].cursor() as cursor:
            # ✅ CHECK DB CONNECTION
            cursor.execute("SELECT DB_NAME()")
            print("Connected DB:", cursor.fetchone())

            # ✅ DEBUG COUNT
            cursor.execute("SELECT COUNT(*) FROM dbo.smart_retail_categories_new")
            print("TOTAL ROWS:", cursor.fetchone())

            # ✅ FETCH DATA
            cursor.execute("SELECT * FROM dbo.smart_categories")
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

            print("RAW ROW COUNT:", len(rows))

            for row in rows:
                row_dict = dict(zip(columns, row))

                # ✅ MAKE JSON SAFE
                for k, v in row_dict.items():
                    if isinstance(v, datetime):
                        row_dict[k] = v.isoformat()
                    elif v is None:
                        row_dict[k] = None
                    elif not isinstance(v, (int, float, bool)):
                        row_dict[k] = str(v)

                categories.append(row_dict)

        print("FINAL CATEGORIES SAMPLE:", categories[:3])
        return categories

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

        categories = self.get_categories_from_db()
        if not categories:
            print("❌ No categories found in DB")
            return

        success = 0
        failed = 0

        for c in categories:
            family_no = c.get("corp_id") or c.get("category_id")
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

            sync_status = 2 if smart_data.get("successful") else 4
            self.update_hais_category_status(hais_token, family_no, anniv, sync_status)

            if sync_status == 2:
                success += 1
            else:
                failed += 1

        print(f"✅ RETAIL CATEGORY SYNC DONE → {success} success, {failed} failed")