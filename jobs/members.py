

import requests
from urllib.parse import urlencode
from django.conf import settings
from engine.models import MemberSyncSuccess, MemberSyncFailure

class SyncHaisMembersService:

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
            if data.get("response", {}).get("status") == 200:
                return data["response"]["result"]["accessToken"]
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
                verify=False,  # ⚠️ Replace with proper certificate verification in production
                timeout=30
            )
            return resp.json().get("access_token")
        except Exception as e:
            print(f"❌ SMART Auth Error: {e}")
        return None

    def get_hais_members(self, hais_token):
        payload = {"name": "smartCorporateMembers", "param": {}}
        try:
            resp = requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers={"Authorization": f"Bearer {hais_token}", "Content-Type": "application/json"},
                timeout=60
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def run(self):
        print("🔄 CORPORATE SYNC STARTED")
        hais_token = self.get_hais_token()
        smart_token = self.get_smart_token()

        if not hais_token or not smart_token:
            print("❌ Authentication failed.")
            return

        members_resp = self.get_hais_members(hais_token)
        if members_resp.get("response", {}).get("status") != 200:
            print("❌ Failed to fetch corporate members")
            return

        members = members_resp["response"]["result"]

        for m in members:
            try:
                # ---------- Safe Name Parsing ----------
                full_name = m.get("member_name") or ""
                names = full_name.split()
                surname = names[0] if len(names) > 0 else ""
                second_name = names[1] if len(names) > 1 else ""
                third_name = names[2] if len(names) > 2 else ""

                # ---------- Safe Phone Parsing ----------
                raw_phone = m.get("mobile_no")
                phone = str(raw_phone).replace(" ", "") if raw_phone else ""
                mobile_phone = f"254{phone[-9:]}" if len(phone) >= 9 else ""

                anniv = m.get("anniv") or ""
                membership_number = m.get("member_no")
                family_code = m.get("family_no")

                payload = {
                    "familyCode": family_code,
                    "membershipNumber": membership_number,
                    "staffNumber": membership_number,
                    "surname": surname,
                    "secondName": second_name,
                    "thirdName": third_name,
                    "otherNames": "",
                    "dob": m.get("dob", ""),
                    "gender": m.get("gender", ""),
                    "memType": m.get("member_type"),
                    "schemeStartDate": m.get("start_date"),
                    "schemeEndDate": m.get("end_date"),
                    "clnCatCode": f"{m.get('category')}-{anniv}",
                    "clnPolCode": m.get("corp_id"),
                    "phone_number": mobile_phone,
                    "email_address": m.get("email", ""),
                    "userID": m.get("user_id"),
                    "country": settings.COUNTRY_CODE,
                    "customerid": settings.SMART_CUSTOMER_ID,
                    "roamingCountries": settings.COUNTRY_CODE
                }

                smart_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(payload)}"
                smart_resp = requests.post(
                    smart_url,
                    headers={"Authorization": f"Bearer {smart_token}"},
                    verify=False,  # ⚠️ Replace in production
                    timeout=60
                )
                smart_data = smart_resp.json()

                db_data = {
                    "member_no": membership_number,
                    "family_no": family_code,
                    "surname": surname,
                    "second_name": second_name,
                    "third_name": third_name,
                    "category": m.get("category"),
                    "anniv": anniv,
                    "corp_id": m.get("corp_id"),
                    "smart_status": smart_resp.status_code,
                    "smart_response": smart_data,
                }

                if bool(smart_data.get("successful")):
                    MemberSyncSuccess.objects.create(**db_data)
                else:
                    MemberSyncFailure.objects.create(**db_data)

            except Exception as e:
                print(f"❌ Error processing member {m.get('member_no')}: {e}")

        print("✅ HAIS Corporate Members sync job executed successfully")
import requests
from urllib.parse import urlencode
from django.conf import settings
from engine.models import MemberSyncSuccess, MemberSyncFailure

class SyncRetailMembersService:

    def get_hais_token(self):
        payload = {
            "name": "generateToken",
            "param": {
                "consumer_key": settings.HAIS_API_CONSUMER_KEY,
                "consumer_secret": settings.HAIS_API_CONSUMER_SECRET
            }
        }
        try:
            resp = requests.post(settings.HAIS_API_BASE_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
            data = resp.json()
            if data.get("response", {}).get("status") == 200:
                return data["response"]["result"]["accessToken"]
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
            resp = requests.post(f"{settings.SMART_ACCESS_TOKEN}{urlencode(payload)}", headers={"Content-Type": "application/x-www-form-urlencoded"}, verify=False, timeout=30)
            return resp.json().get("access_token")
        except Exception as e:
            print(f"❌ SMART Auth Error: {e}")
        return None

    def get_hais_members(self, hais_token):
        payload = {"name": "smartRetailMembers", "param": {}}
        try:
            resp = requests.post(settings.HAIS_API_BASE_URL, json=payload, headers={"Authorization": f"Bearer {hais_token}", "Content-Type": "application/json"}, timeout=60)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def run(self):
        print("🔄 RETAIL SYNC STARTED")
        hais_token = self.get_hais_token()
        smart_token = self.get_smart_token()

        if not hais_token or not smart_token:
            print("❌ Authentication failed.")
            return

        members_resp = self.get_hais_members(hais_token)
        if members_resp.get("response", {}).get("status") != 200:
            print("❌ Failed to fetch retail members")
            return

        members = members_resp["response"]["result"]

        for m in members:
            try:
                member_names = m.get("member_name", "").split()
                surname = member_names[0] if len(member_names) > 0 else ""
                second_name = member_names[1] if len(member_names) > 1 else ""
                third_name = member_names[2] if len(member_names) > 2 else ""

                anniv = m.get("anniv")
                family_code = m.get("family_no")
                membership_number = m.get("member_no")

                phone = m.get("mobile_no", "").replace(" ", "")
                mobile_phone = f"254{phone[-9:]}" if phone else ""

                payload = {
                    "familyCode": family_code,
                    "membershipNumber": membership_number,
                    "staffNumber": membership_number,
                    "surname": surname,
                    "secondName": second_name,
                    "thirdName": third_name,
                    "otherNames": "",
                    "dob": m.get("dob", ""),
                    "gender": m.get("gender", ""),
                    "memType": m.get("memType"),
                    "schemeStartDate": m.get("start_date"),
                    "schemeEndDate": m.get("end_date"),
                    "clnCatCode": f"{family_code}-{anniv}",
                    "clnPolCode": m.get("scheme_id"),
                    "phone_number": mobile_phone,
                    "email_address": m.get("email", ""),
                    "userID": m.get("user_id"),
                    "country": settings.COUNTRY_CODE,
                    "customerid": settings.SMART_CUSTOMER_ID,
                    "roamingCountries": settings.COUNTRY_CODE
                }

                smart_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(payload)}"
                smart_resp = requests.post(smart_url, headers={"Authorization": f"Bearer {smart_token}"}, verify=False, timeout=60)
                smart_data = smart_resp.json()

                db_data = {
                    "member_no": membership_number,
                    "family_no": family_code,
                    "surname": surname,
                    "second_name": second_name,
                    "third_name": third_name,
                    "category": m.get("memType"),
                    "anniv": anniv,
                    "corp_id": m.get("scheme_id"),
                    "smart_status": smart_resp.status_code,
                    "smart_response": smart_data,
                }

                if bool(smart_data.get("successful")):
                    MemberSyncSuccess.objects.create(**db_data)
                else:
                    MemberSyncFailure.objects.create(**db_data)

            except Exception as e:
                print(f"❌ Error processing retail member {m.get('member_no')}: {e}")

        print("✅ HAIS Retail Members sync job executed successfully")