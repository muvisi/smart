
import os
import json
import requests
from urllib.parse import urlencode
from django.conf import settings
from engine.models import MemberSyncSuccess, MemberSyncFailure


class SyncHaisMembersService:

    def get_hais_token(self):
        """Fetch HAIS token"""
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
        """Fetch SMART token"""
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
            return resp.json().get("access_token")
        except Exception as e:
            print(f"❌ SMART Auth Error: {e}")
        return None

    def get_hais_members(self, hais_token):
        """Fetch members from HAIS"""
        payload = {"name": "smartCorporateMembers", "param": {}}
        headers = {
            "Authorization": f"Bearer {hais_token}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers=headers,
                timeout=60
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def update_hais_member_sync(self, hais_token, member_no, anniv, status):
        """Update HAIS member sync status"""
        payload = {
            "name": "updateSmartMember",
            "param": {"member_no": member_no, "anniv": anniv, "status": status}
        }
        headers = {"Authorization": f"Bearer {hais_token}", "Content-Type": "application/json"}
        try:
            requests.post(settings.HAIS_API_BASE_URL, json=payload, headers=headers, verify=False)
        except Exception as e:
            print(f"❌ HAIS update error for member {member_no}: {e}")

    def run(self):
        print("🔄 HAIS CORPORATE MEMBERS SYNC STARTED")

        hais_token = self.get_hais_token()
        smart_token = self.get_smart_token()

        if not hais_token:
            print("❌ Failed to get HAIS token")
            return

        if not smart_token:
            print("❌ Failed to get SMART token")
            return

        members_resp = self.get_hais_members(hais_token)
        if members_resp.get("response", {}).get("status") != 200:
            print("❌ Failed to fetch members")
            return

        members = members_resp["response"]["result"]
        success, failed = 0, 0

        for m in members:
            try:
                # -------- Name Parsing --------
                full_name = m.get("member_name", "")
                names = full_name.split()
                surname = names[0] if len(names) > 0 else ""
                second_name = names[1] if len(names) > 1 else ""
                third_name = names[2] if len(names) > 2 else ""

                # -------- Phone Parsing --------
                raw_phone = m.get("mobile_no", "")
                phone = str(raw_phone).replace(" ", "")
                if phone.startswith("0"):
                    mobile_phone = f"254{phone[1:]}"
                elif phone.startswith("254"):
                    mobile_phone = phone
                else:
                    mobile_phone = phone

                anniv = m.get("anniv", "")
                membership_number = m.get("member_no")
                family_code = m.get("family_no")

                # -------- SMART PAYLOAD --------
                smart_payload = {
                    "familyCode": family_code,
                    "membershipNumber": membership_number,
                    "staffNumber": membership_number,
                    "surname": surname,
                    "secondName": second_name,
                    "thirdName": third_name,
                    "otherNames": "",
                    "dob": m.get("dob", ""),
                    "gender": m.get("gender", ""),
                    "memType": m.get("member_type", ""),
                    "schemeStartDate": m.get("start_date", ""),
                    "schemeEndDate": m.get("end_date", ""),
                    "clnCatCode": f"{m.get('category', '')}-{anniv}",
                    "clnPolCode": m.get("corp_id", ""),
                    "phone_number": mobile_phone,
                    "email_address": m.get("email", ""),
                    "userID": m.get("user_id", ""),
                    "country": settings.COUNTRY_CODE,
                    "customerid": settings.SMART_CUSTOMER_ID,
                    "roamingCountries": settings.COUNTRY_CODE
                }

                smart_url = f"{settings.SMART_API_BASE_URL}members"

                smart_resp = requests.post(
                    smart_url,
                    data=smart_payload,
                    headers={
                        "Authorization": f"Bearer {smart_token}",
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    verify=False,
                    timeout=60
                )

                try:
                    smart_data = smart_resp.json()
                except Exception:
                    smart_data = {"raw_response": smart_resp.text}

                # -------- Determine sync status --------
                sync_status = 1 if smart_data.get("successful") else 2

                # -------- Update HAIS member sync --------
                self.update_hais_member_sync(hais_token, membership_number, anniv, sync_status)

                # -------- DATABASE RECORD --------
                db_data = {
                    "member_no": membership_number,
                    "family_no": family_code,
                    "request_object": smart_payload,
                    "surname": surname,
                    "second_name": second_name,
                    "third_name": third_name,
                    "other_names": "",
                    "category": m.get("category", ""),
                    "anniv": anniv,
                    "corp_id": m.get("corp_id", ""),
                    "smart_status": smart_resp.status_code,
                    "smart_response": smart_data
                }

                if sync_status == 1:
                    MemberSyncSuccess.objects.create(**db_data)
                    success += 1
                else:
                    MemberSyncFailure.objects.create(**db_data)
                    failed += 1

            except Exception as e:
                print(f"❌ Error processing member {m.get('member_no')}: {e}")
                failed += 1

        print(f"✅ HAIS MEMBERS SYNC DONE → {success} success, {failed} failed")
        
        
        
        
        
        
import os
import json
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
            resp = requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            data = resp.json()
            print("HAIS auth response:\n", data)
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
                settings.SMART_ACCESS_TOKEN,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                verify=False,
                timeout=30
            )
            data = resp.json()
            print("SMART auth response:\n", data)
            return data.get("access_token")
        except Exception as e:
            print(f"❌ SMART Auth Error: {e}")
        return None

    def get_hais_members(self, hais_token):
        payload = {"name": "smartRetailMembers", "param": {}}
        headers = {"Authorization": f"Bearer {hais_token}", "Content-Type": "application/json"}
        try:
            resp = requests.post(settings.HAIS_API_BASE_URL, json=payload, headers=headers, verify=False)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def update_hais_member_sync(self, member_no, anniv, status):
        payload = {
            "name": "updateSmartMember",
            "param": {"member_no": member_no, "anniv": anniv, "status": status}
        }
        headers = {"Authorization": f"Bearer {self.hais_token}", "Content-Type": "application/json"}
        try:
            requests.post(settings.HAIS_API_BASE_URL, json=payload, headers=headers, verify=False)
        except Exception as e:
            print(f"❌ HAIS update error for member {member_no}: {e}")

    def log_api_request(self, member, response, status_code):
        payload = {
            "name": "createApiLog",
            "param": {
                "source": "HAIS-SMART",
                "transactionName": "Retail Member",
                "statusCode": status_code,
                "requestObject": [json.dumps(member)],
                "responseObject": [response]
            }
        }
        headers = {"Authorization": f"Bearer {self.hais_token}", "Content-Type": "application/json"}
        try:
            requests.post(settings.HAIS_API_BASE_URL, json=payload, headers=headers, verify=False)
        except Exception as e:
            print(f"❌ HAIS API log error: {e}")

    def run(self):
        print("🔄 RETAIL SYNC STARTED")

        self.hais_token = self.get_hais_token()
        smart_token = self.get_smart_token()

        if not self.hais_token or not smart_token:
            print("❌ Authentication failed.")
            return

        members_resp = self.get_hais_members(self.hais_token)
        if members_resp.get("response", {}).get("status") != 200:
            print("❌ Failed to fetch retail members")
            return

        members = members_resp["response"]["result"]
        success = 0
        failed = 0

        for member in members:
            try:
                member_names = member.get("member_name", "").split()
                surname = member_names[0] if len(member_names) > 0 else ""
                secondName = member_names[1] if len(member_names) > 1 else ""
                thirdName = member_names[2] if len(member_names) > 2 else ""
                otherNames = ""

                anniv = member.get("anniv")
                familyCode = member.get("family_no")
                membershipNumber = member.get("member_no")
                phone = (member.get("mobile_no") or "").replace(" ", "")
                mobilePhone = f"254{phone[-9:]}" if phone else ""

                smart_payload = {
                    "familyCode": familyCode,
                    "membershipNumber": membershipNumber,
                    "staffNumber": membershipNumber,
                    "surname": surname,
                    "secondName": secondName,
                    "thirdName": thirdName,
                    "otherNames": otherNames,
                    "dob": member.get("dob", ""),
                    "gender": member.get("gender", ""),
                    "memType": member.get("memType"),
                    "schemeStartDate": member.get("start_date"),
                    "schemeEndDate": member.get("end_date"),
                    "clnCatCode": f"{familyCode}-{anniv}",
                    "clnPolCode": member.get("scheme_id"),
                    "phone_number": mobilePhone,
                    "email_address": member.get("email", ""),
                    "userID": member.get("user_id"),
                    "country": settings.COUNTRY_CODE,
                    "customerid": settings.SMART_CUSTOMER_ID,
                    "roamingCountries": settings.COUNTRY_CODE
                }

                smart_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(smart_payload)}"
                smart_resp = requests.post(
                    smart_url,
                    headers={"Authorization": f"Bearer {smart_token}"},
                    verify=False,
                    timeout=60
                )

                try:
                    smart_data = smart_resp.json()
                except:
                    smart_data = {"raw_response": smart_resp.text}

                sync_status = 1 if smart_data.get("successful") else 2

                # Update HAIS member sync status
                self.update_hais_member_sync(membershipNumber, anniv, sync_status)

                # Log API request/response
                self.log_api_request(member, smart_resp.text, smart_resp.status_code)

                # Save to DB
                db_data = {
                    "member_no": membershipNumber,
                    "family_no": familyCode,
                    "request_object": smart_payload,
                    "surname": surname,
                    "second_name": secondName,
                    "third_name": thirdName,
                    "other_names": otherNames,
                    "category": member.get("memType"),
                    "anniv": anniv,
                    "corp_id": member.get("scheme_id"),
                    "smart_status": smart_resp.status_code,
                    "smart_response": smart_data,
                }

                if sync_status == 1:
                    MemberSyncSuccess.objects.create(**db_data)
                    success += 1
                else:
                    MemberSyncFailure.objects.create(**db_data)
                    failed += 1

            except Exception as e:
                print(f"❌ Error processing member {member.get('member_no')}: {e}")
                failed += 1

        print(f"✅ HAIS Retail Members sync completed. Success: {success}, Failed: {failed}")