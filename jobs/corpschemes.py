# services/sync_schemes_db_full.py

import json
from urllib.parse import urlencode
from datetime import datetime
from django.conf import settings
from django.db import connections
from engine.models import ApiSyncLog
import requests


class SyncHaisSchemesService:

    # ---------------------------------
    # ✅ FETCH SCHEMES FROM MSSQL
    # ---------------------------------
    def get_schemes(self):
        schemes = []

        with connections['external_mssql'].cursor() as cursor:
            # ✅ CHECK DB CONNECTION (SEPARATE QUERY)
            cursor.execute("SELECT DB_NAME()")
            print("Connected DB:", cursor.fetchone())

            # ✅ OPTIONAL DEBUG COUNT
            cursor.execute("SELECT COUNT(*) FROM dbo.smart_schemes")
            print("TOTAL ROWS:", cursor.fetchone())

            # ✅ MAIN QUERY
            cursor.execute("SELECT TOP 10 * FROM dbo.smart_schemes")

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

                schemes.append(row_dict)

        print("FINAL SCHEMES SAMPLE:", schemes[:3])
        return schemes

    # ---------------------------------
    # ✅ SEND TO SMART
    # ---------------------------------
    def post_to_smart(self, scheme, smart_token):
        payload = {
            "companyName": scheme.get("scheme_name"),
            "clnPolCode": scheme.get("corp_id"),
            "startDate": scheme.get("start_date"),
            "endDate": scheme.get("end_date"),
            "polTypeId": scheme.get("scheme_type_id"),
            "userId": scheme.get("user_id"),
            "anniv": scheme.get("anniv"),
            "policyCurrencyId": getattr(settings, "POLICY_CURRENCY_ID", "KES"),
            "countryCode": getattr(settings, "COUNTRY_CODE", "KE"),
            "customerid": settings.SMART_CUSTOMER_ID
        }

        url = f"{settings.SMART_API_BASE_URL}schemes?{urlencode(payload)}"

        print("\n💡 SMART PAYLOAD:\n", json.dumps(payload, indent=2))

        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {smart_token}"},
                verify=False,
                timeout=60
            )

            try:
                data = resp.json()
            except:
                data = {"raw_response": resp.text}

            status = 1 if data.get("successful") else 2
            return status, data

        except Exception as e:
            print(f"❌ SMART ERROR: {e}")
            return 2, {"error": str(e)}

    # ---------------------------------
    # ✅ LOG
    # ---------------------------------
    def log_api_request(self, scheme, response, status_code):
        try:
            ApiSyncLog.objects.create(
                api_name="SyncDBToSmart",
                transaction_name=f"{scheme.get('scheme_type')} Scheme: {scheme.get('scheme_name')}",
                request_object=scheme,
                response_object=response,
                status=status_code,
                http_code=status_code
            )
        except Exception as e:
            print(f"❌ Logging error: {e}")

    # ---------------------------------
    # ✅ UPDATE SYNC STATUS IN DB
    # ---------------------------------
    def mark_scheme_synced(self, scheme, status):
        with connections['external_mssql'].cursor() as cursor:
            try:
                cursor.execute(
                    """
                    UPDATE dbo.corporate
                    SET sync=1
                    WHERE corp_id=%s 
                    """,
                    [status]
                )
            except Exception as e:
                print(f"❌ DB update error for {scheme.get('corp_id')}: {e}")

    # ---------------------------------
    # ✅ GET SMART TOKEN
    # ---------------------------------
    def get_smart_token(self):
        try:
            payload = {
                "client_id": settings.SMART_CLIENT_ID,
                "client_secret": settings.SMART_CLIENT_SECRET,
                "grant_type": settings.SMART_GRANT_TYPE
            }

            resp = requests.post(
                settings.SMART_ACCESS_TOKEN,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                verify=False,
                timeout=30
            )

            return resp.json().get("access_token")

        except Exception as e:
            print(f"❌ SMART Auth Error: {e}")
            return None

    # ---------------------------------
    # ✅ MAIN RUNNER
    # ---------------------------------
    def run(self):
        print("🔄 DB SCHEMES SYNC STARTED")

        smart_token = self.get_smart_token()

        if not smart_token:
            print("❌ Failed to get SMART token")
            return

        schemes = self.get_schemes()

        if not schemes:
            print("❌ No schemes retrieved from DB")
            return

        success, failed = 0, 0

        for scheme in schemes:
            status, response = self.post_to_smart(scheme, smart_token)

            self.log_api_request(scheme, response, status)
            self.mark_scheme_synced(scheme, status)
            print("scheme pposted",scheme,status)

            if status == 1:
                success += 1
            else:
                failed += 1

        print(f"✅ DONE → Success: {success}, Failed: {failed}")