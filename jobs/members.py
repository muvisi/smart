import requests
from urllib.parse import urlencode
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
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
            # Note: verify=False is used per your requirement for SMART SSL
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

    def get_hais_members(self, hais_token):
        payload = {"name": "smartCorporateMembers", "param": {}}
        try:
            resp = requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {hais_token}",
                    "Content-Type": "application/json"
                },
                timeout=60
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def send_email_summary(self, members_summary, success_count, failed_count):
        """Send email with synced members summary using template."""
        try:
            subject = f"[Madison Healthcare] HAIS Corporate Members Sync Report"
            html_content = render_to_string("emails/members_summary.html", {
                "members": members_summary,
                "success_count": success_count,
                "failed_count": failed_count,
            })
            email = EmailMessage(
                subject,
                html_content,
                settings.EMAIL_HOST_USER, # Ensure this is a valid 'from' address
                ["mwangangimuvisi@gmail.com"],
            )
            email.content_subtype = "html"
            email.send(fail_silently=False)
            print("✅ Corporate Summary email sent successfully")
        except Exception as e:
            print(f"❌ Failed to send Corporate email: {e}")

    def run(self):
        hais_token = self.get_hais_token()
        smart_token = self.get_smart_token()
        if not hais_token or not smart_token:
            print("❌ Authentication failed. Check API credentials.")
            return

        members_resp = self.get_hais_members(hais_token)
        if members_resp.get("response", {}).get("status") != 200:
            print("❌ Failed to fetch members")
            return

        members = members_resp["response"]["result"]
        success, failed = 0, 0
        members_summary = []

        for m in members:
            try:
                names = m.get("member_name", "").split(" ")
                surname = names[0] if len(names) > 0 else ""
                second_name = names[1] if len(names) > 1 else ""
                third_name = names[2] if len(names) > 2 else ""
                
                phone = m.get("mobile_no", "").replace(" ", "")
                mobile_phone = f"254{phone[-9:]}" if phone else ""
                anniv = m.get("anniv")

                payload = {
                    "familyCode": m.get("family_no"),
                    "membershipNumber": m.get("member_no"),
                    "staffNumber": m.get("member_no"),
                    "surname": surname,
                    "secondName": second_name,
                    "thirdName": third_name,
                    "otherNames": "null",
                    "dob": m.get("dob", "null"),
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
                smart_resp = requests.post(smart_url, headers={"Authorization": f"Bearer {smart_token}"}, verify=False)
                smart_data = smart_resp.json()
                smart_httpcode = smart_resp.status_code

                is_successful = smart_data.get("successful")
                sync_status = 1 if is_successful else 2

                summary = {
                    "member_no": m.get("member_no"),
                    "family_no": m.get("family_no"),
                    "surname": surname,
                    "second_name": second_name,
                    "third_name": third_name,
                    "other_names": "null",
                    "category": m.get("category"),
                    "anniv": anniv,
                    "corp_id": m.get("corp_id"),
                    "smart_status": smart_httpcode,
                    "smart_successful": is_successful,
                    "smart_response": smart_data
                }
                members_summary.append(summary)

                if sync_status == 1:
                    success += 1
                    MemberSyncSuccess.objects.create(**summary)
                else:
                    failed += 1
                    MemberSyncFailure.objects.create(**summary)

            except Exception as e:
                failed += 1
                print(f"❌ Error processing member {m.get('member_no')}: {e}")

        self.send_email_summary(members_summary, success, failed)
        
        
        
        
# class SyncRetailMembersService:
#     # ... (get_hais_token and get_smart_token remain same as above) ...

#     def send_email_summary(self, members_summary, success_count, failed_count):
#         try:
#             subject = f"[Madison Healthcare] HAIS Retail Members Sync Report"
#             html_content = render_to_string("emails/members_summary.html", {
#                 "members": members_summary,
#                 "success_count": success_count,
#                 "failed_count": failed_count,
#             })
#             email = EmailMessage(
#                 subject, html_content, settings.EMAIL_HOST_USER, ["mwangangimuvisi@gmail.com"]
#             )
#             email.content_subtype = "html"
#             email.send(fail_silently=False)
#             print("✅ Retail Summary email sent")
#         except Exception as e:
#             print(f"❌ Failed to send Retail email: {e}")

#     def run(self):
#         print("🔄 RETAIL SYNC STARTED")
#         hais_token = self.get_hais_token()
#         smart_token = self.get_smart_token()
#         if not hais_token or not smart_token: return

#         members_resp = self.get_hais_members(hais_token)
#         members = members_resp["response"]["result"]
#         success, failed, members_summary = 0, 0, []

#         for m in members:
#             try:
#                 cln_pol_code = m.get("scheme_id")
#                 membership_number = m.get("member_no")
#                 family_code = m.get("family_no")
#                 anniv = m.get("anniv")
                
#                 member_names = m.get("member_name", "").split(" ")
#                 surname = member_names[0] if len(member_names) > 0 else ""
#                 second_name = member_names[1] if len(member_names) > 1 else ""
                
#                 payload = {
#                     "familyCode": family_code,
#                     "membershipNumber": membership_number,
#                     "staffNumber": membership_number,
#                     "surname": surname,
#                     "secondName": second_name,
#                     "thirdName": member_names[2] if len(member_names) > 2 else "",
#                     "otherNames": "",
#                     "dob": m.get("dob", ""),
#                     "gender": m.get("gender", ""),
#                     "memType": m.get("memType"),
#                     "schemeStartDate": m.get("start_date"),
#                     "schemeEndDate": m.get("end_date"),
#                     "clnCatCode": f"{family_code}-{anniv}",
#                     "clnPolCode": cln_pol_code,
#                     "phone_number": f"254{m.get('mobile_no', '')[-9:]}" if m.get('mobile_no') else "",
#                     "email_address": m.get("email", ""),
#                     "userID": m.get("user_id"),
#                     "country": settings.COUNTRY_CODE,
#                     "customerid": settings.SMART_CUSTOMER_ID,
#                     "roamingCountries": settings.COUNTRY_CODE
#                 }

#                 smart_url = f"{settings.SMART_API_BASE_URL}members?{urlencode(payload)}"
#                 smart_resp = requests.post(smart_url, headers={"Authorization": f"Bearer {smart_token}"}, verify=False)
#                 smart_data = smart_resp.json()
                
#                 is_successful = smart_data.get("successful")
                
#                 summary = {
#                     "member_no": membership_number,
#                     "family_no": family_code,
#                     "surname": surname,
#                     "second_name": second_name,
#                     "third_name": payload["thirdName"],
#                     "other_names": "",
#                     "category": m.get("memType"),
#                     "anniv": anniv,
#                     "corp_id": cln_pol_code,
#                     "smart_status": smart_resp.status_code,
#                     "smart_successful": is_successful,
#                     "smart_response": smart_data
#                 }
#                 members_summary.append(summary)

#                 if is_successful:
#                     success += 1
#                     MemberSyncSuccess.objects.create(**summary)
#                 else:
#                     failed += 1
#                     MemberSyncFailure.objects.create(**summary)

#             except Exception as e:
#                 failed += 1
#                 print(f"❌ Error retail member {m.get('member_no')}: {e}")

#         self.send_email_summary(members_summary, success, failed)

import requests
from urllib.parse import urlencode
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from engine.models import MemberSyncSuccess, MemberSyncFailure


class SyncRetailMembersService:

    # =============================
    # AUTH METHODS
    # =============================

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
                verify=False,
                timeout=30
            )

            return resp.json().get("access_token")

        except Exception as e:
            print(f"❌ SMART Auth Error: {e}")

        return None

    # =============================
    # FETCH MEMBERS
    # =============================

    def get_hais_members(self, hais_token):
        payload = {"name": "smartRetailMembers", "param": {}}

        try:
            resp = requests.post(
                settings.HAIS_API_BASE_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {hais_token}",
                    "Content-Type": "application/json"
                },
                timeout=60
            )

            return resp.json()

        except Exception as e:
            return {"error": str(e)}

    # =============================
    # EMAIL SUMMARY
    # =============================

    def send_email_summary(self, members_summary, success_count, failed_count):
        total = success_count + failed_count

        sync_quality = round(
            (success_count / total) * 100, 2
        ) if total > 0 else 0

        try:
            subject = "[Madison Healthcare] HAIS Retail Members Sync Report"

            html_content = render_to_string(
                "emails/members_summary.html",
                {
                    "members": members_summary,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "sync_quality": sync_quality,
                }
            )

            email = EmailMessage(
                subject,
                html_content,
                settings.EMAIL_HOST_USER,
                ["mwangangimuvisi@gmail.com"],
            )

            email.content_subtype = "html"
            email.send(fail_silently=False)

            print("✅ Retail Summary email sent successfully")

        except Exception as e:
            print(f"❌ Failed to send Retail email: {e}")

    # =============================
    # MAIN RUN METHOD
    # =============================

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

        success = 0
        failed = 0
        members_summary = []

        for m in members:
            try:
                # -------------------------
                # Parse names safely
                # -------------------------
                member_names = m.get("member_name", "").split()
                surname = member_names[0] if len(member_names) > 0 else ""
                second_name = member_names[1] if len(member_names) > 1 else ""
                third_name = member_names[2] if len(member_names) > 2 else ""

                anniv = m.get("anniv")
                family_code = m.get("family_no")
                membership_number = m.get("member_no")

                # Format phone
                phone = m.get("mobile_no", "").replace(" ", "")
                mobile_phone = f"254{phone[-9:]}" if phone else ""

                # -------------------------
                # SMART PAYLOAD
                # -------------------------
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

                smart_resp = requests.post(
                    smart_url,
                    headers={"Authorization": f"Bearer {smart_token}"},
                    verify=False,
                    timeout=60
                )

                smart_data = smart_resp.json()
                smart_httpcode = smart_resp.status_code

                is_successful = bool(smart_data.get("successful"))

                # -------------------------
                # EMAIL SUMMARY DATA
                # -------------------------
                summary = {
                    "member_no": membership_number,
                    "family_no": family_code,
                    "surname": surname,
                    "second_name": second_name,
                    "third_name": third_name,
                    "category": m.get("memType"),
                    "anniv": anniv,
                    "corp_id": m.get("scheme_id"),
                    "smart_status": smart_httpcode,
                    "smart_successful": is_successful,
                }

                members_summary.append(summary)

                # -------------------------
                # DATABASE SAVE (ONLY MODEL FIELDS)
                # -------------------------
                db_data = {
                    "member_no": membership_number,
                    "family_no": family_code,
                    "surname": surname,
                    "second_name": second_name,
                    "third_name": third_name,
                    "category": m.get("memType"),
                    "anniv": anniv,
                    "corp_id": m.get("scheme_id"),
                    "smart_status": smart_httpcode,
                    "smart_response": smart_data,
                }

                if is_successful:
                    success += 1
                    MemberSyncSuccess.objects.create(**db_data)
                else:
                    failed += 1
                    MemberSyncFailure.objects.create(**db_data)

            except Exception as e:
                failed += 1
                print(f"❌ Error processing retail member {m.get('member_no')}: {e}")

        # -------------------------
        # SEND EMAIL
        # -------------------------
        self.send_email_summary(members_summary, success, failed)

        print("✅ HAIS Retail Members sync job executed successfully")