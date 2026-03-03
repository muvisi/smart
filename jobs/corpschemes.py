import requests
from urllib.parse import urlencode
from django.conf import settings
from engine.models import ApiSyncLog

class SyncSchemesService:
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
            data = resp.json()
            return data.get("response", {}).get("result", {}).get("accessToken")
        except Exception as e:
            print(f"❌ HAIS Auth Error: {e}")
            return None

    def get_smart_token(self):
        payload = {
            "client_id": settings.SMART_CLIENT_ID,
            "client_secret": settings.SMART_CLIENT_SECRET,
            "grant_type": settings.SMART_GRANT_TYPE
        }
        try:
            resp = requests.post(
                f"{settings.SMART_ACCESS_TOKEN}{urlencode(payload)}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                verify=False,
                timeout=30
            )
            return resp.json().get("access_token")
        except Exception as e:
            print(f"❌ SMART Auth Error: {e}")
            return None

    def run(self):
        print("🔄 SCHEME SYNC STARTED")
        hais_token = self.get_hais_token()
        smart_token = self.get_smart_token()

        if not hais_token or not smart_token:
            print("❌ Authentication failed. Skipping sync.")
            return

        try:
            schemes_resp = requests.post(
                settings.HAIS_API_BASE_URL,
                json={"name": "smartSchemes", "param": {}},
                headers={"Authorization": f"Bearer {hais_token}", "Content-Type": "application/json"},
                timeout=30
            ).json()
        except Exception as e:
            print(f"❌ Failed to fetch schemes from HAIS: {e}")
            return

        if schemes_resp.get("response", {}).get("status") != 200:
            print(f"❌ HAIS returned error status: {schemes_resp}")
            return

        schemes = schemes_resp["response"]["result"]

        for s in schemes:
            url_data = {
                "companyName": s.get("scheme_name"),
                "clnPolCode": s.get("corp_id"),
                "startDate": s.get("start_date"),
                "endDate": s.get("end_date"),
                "polTypeId": s.get("scheme_type_id"),
                "userId": s.get("user_id"),
                "anniv": s.get("anniv"),
                "policyCurrencyId": settings.POLICY_CURRENCY_ID,
                "countryCode": settings.COUNTRY_CODE,
                "customerid": settings.SMART_CUSTOMER_ID
            }
            smart_url = f"{settings.SMART_API_BASE_URL}schemes?{urlencode(url_data)}"

            try:
                smart_resp = requests.post(
                    smart_url,
                    headers={"Authorization": f"Bearer {smart_token}"},
                    verify=False,
                    timeout=30
                )
                smart_data = smart_resp.json()
                smart_httpcode = smart_resp.status_code
            except Exception as e:
                smart_data = {"error": str(e)}
                smart_httpcode = 500

            is_successful = str(smart_data.get("successful")).lower() == "true"
            sync_status = 1 if is_successful else 2

            # Update HAIS
            update_req = {
                "name": "updateCorporateScheme" if s.get("scheme_type") == "CORPORATE" else "updateRetailScheme",
                "param": {
                    "corp_id": s.get("corp_id"),
                    "anniv": s.get("anniv") if s.get("scheme_type") == "CORPORATE" else None,
                    "status": sync_status
                }
            }
            try:
                requests.post(
                    settings.HAIS_API_BASE_URL,
                    json=update_req,
                    headers={"Authorization": f"Bearer {hais_token}", "Content-Type": "application/json"},
                    timeout=30
                )
            except Exception:
                pass

            # Fixed field names: request_object and response_object
            ApiSyncLog.objects.create(
                api_name="SyncHaisToSmart",
                transaction_name=f"{s.get('scheme_type').capitalize()} Scheme: {s.get('scheme_name')}",
                request_object=s,
                response_object=smart_data,
                status=sync_status,
                http_code=smart_httpcode
            )

        print("✅ HAIS Schemes sync job executed successfully")