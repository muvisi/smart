import requests
import logging
from urllib.parse import urlencode
from django.conf import settings
from django.db import connections

from engine.models import CopaySync
# from intergration.models import CopaySync

logger = logging.getLogger(__name__)


class SmartCorpCopaySyncService:

    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.mssql_alias = getattr(settings, "EXTERNAL_MSSQL_ALIAS", "external_mssql")
        self.smart_token = None

    # ==============================
    # 1. GET SMART TOKEN
    # ==============================
    def _get_smart_token(self):
        try:
            payload = {
                "client_id": settings.SMART_CLIENT_ID,
                "client_secret": settings.SMART_CLIENT_SECRET,
                "grant_type": settings.SMART_GRANT_TYPE,
            }

            res = self.session.post(
                settings.SMART_ACCESS_TOKEN,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )

            return res.json().get("access_token")

        except Exception as e:
            logger.error(f"SMART TOKEN ERROR: {e}")
            return None

    # ==============================
    # 2. FETCH FROM MSSQL
    # ==============================
    def _get_copays(self):
        with connections[self.mssql_alias].cursor() as cursor:
            cursor.execute("""
                SELECT TOP 100 *
                FROM smart_corp_copay_new
                
            """)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        return [dict(zip(columns, row)) for row in rows]

    # ==============================
    # 3. UPDATE MSSQL STATUS
    # ==============================
    def _update_status(self, cursor, idx, status):
        cursor.execute(
            "UPDATE corp_provider SET sync = %s WHERE idx = %s",
            [status, idx]
        )

    # ==============================
    # 4. CREATE LOG (PENDING)
    # ==============================
    def _create_log(self, val, payload, endpoint):
        try:
            return CopaySync.objects.create(
                transaction_name="Corporate Scheme Copay",
                endpoint=endpoint,
                status=3,  # PENDING
                request_object=payload,
                corp_id=str(val.get("corp_id")),
                reference_id=str(val.get("idx")),
            )
        except Exception as e:
            logger.error(f"LOG CREATE ERROR: {e}")
            return None

    # ==============================
    # 5. UPDATE LOG
    # ==============================
    def _update_log(self, log, status, status_code, response, error=None):
        try:
            if not log:
                return

            log.status = status
            log.status_code = status_code
            log.response_object = response
            log.error_message = error
            log.save(update_fields=[
                "status",
                "status_code",
                "response_object",
                "error_message",
                "updated_at"
            ])
        except Exception as e:
            logger.error(f"LOG UPDATE ERROR: {e}")

    # ==============================
    # 6. MAIN SYNC
    # ==============================
    def run_sync(self):
        logger.info("🚀 CORPORATE COPAY SYNC STARTED")

        success = 0
        failed = 0

        records = self._get_copays()

        if not records:
            return {"status": "success", "message": "No records found"}

        self.smart_token = self._get_smart_token()
        if not self.smart_token:
            return {"status": "error", "message": "SMART token failed"}

        with connections[self.mssql_alias].cursor() as cursor:

            for val in records:
                idx = val.get("idx")

                payload = {
                    "integ_scheme_code": str(val.get("corp_id", "")),
                    "integ_cat_code": str(val.get("smart_copay_category", "")),
                    "integ_ben_code": str(val.get("benefit_code", "")),
                    "integ_prov_code": str(val.get("provider_code", "")),
                    "integ_service_code": str(val.get("service_code", "")),
                    "copay_type": int(val.get("copay_type") or 0),
                    "amount": float(val.get("copay_amt") or 0.0),
                }

                params = {
                    "country": "KE",
                    "customerid": settings.SMART_CUSTOMER_ID
                }

                url = f"{settings.SMART_API_BASE_URL}copay/setup?{urlencode(params)}"

                # 🔹 CREATE PENDING LOG
                log = self._create_log(val, payload, url)

                try:
                    res = self.session.post(
                        url,
                        json=payload,
                        headers={"Authorization": f"Bearer {self.smart_token}"},
                        timeout=30
                    )

                    status_code = res.status_code

                    try:
                        res_data = res.json()
                    except Exception:
                        res_data = {"raw": res.text}

                    is_ok = res_data.get("successful") is True or \
                            str(res_data.get("successful")).lower() == "true"

                    sync_status = 1 if is_ok else 2

                    # 🔹 UPDATE MSSQL
                    self._update_status(cursor, idx, sync_status)

                    # 🔹 UPDATE LOG
                    if is_ok:
                        self._update_log(log, 1, status_code, res_data)
                        success += 1
                        logger.info(f"✅ SUCCESS idx={idx}")
                    else:
                        self._update_log(log, 2, status_code, res_data, error=str(res_data))
                        failed += 1
                        logger.error(f"❌ FAILED idx={idx}")

                except Exception as e:
                    # 🔹 UPDATE MSSQL
                    self._update_status(cursor, idx, 2)

                    # 🔹 UPDATE LOG
                    self._update_log(
                        log,
                        2,
                        500,
                        {"error": str(e)},
                        error=str(e)
                    )

                    failed += 1
                    logger.error(f"❌ ERROR idx={idx} → {e}")

        return {
            "status": "success",
            "message": f"{success} synced, {failed} failed"
        }