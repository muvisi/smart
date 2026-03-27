# engine/tasks/member_sync_reset.py
from django.db import connections, transaction
from django.conf import settings
from .models import MemberSyncResetLog

class SmartMemberResetService:
    def __init__(self):
        self.mssql_alias = getattr(settings, 'EXTERNAL_MSSQL_ALIAS', 'external_mssql')
        self.audit_db = 'default'

    def run_member_reset_sync(self, batch_size=25):
        """Fetch family_no + anniv and reset sync flags in MSSQL, logging each reset."""
        print("\n🔄 MEMBER SYNC RESET STARTED")
        stats = {"success": 0, "failed": 0, "total": 0}

        try:
            with connections[self.mssql_alias].cursor() as cursor:
                # Fetch pending families
                query = f"""
                SELECT TOP {batch_size} 
                    mi.family_no,
                    MAX(ma.anniv) AS anniv
                FROM dbo.member_anniversary ma
                INNER JOIN dbo.member_info mi
                    ON ma.member_no = mi.member_no
                INNER JOIN dbo.principal_applicant pa
                    ON mi.family_no = pa.family_no
                WHERE ma.sync IS NULL
                    AND GETDATE() BETWEEN ma.start_date AND ma.end_date
                    AND pa.individual = 2
                    AND ISNULL(mi.cancelled,0) IN (0,3)
                GROUP BY mi.family_no
                """
                cursor.execute(query)
                rows = cursor.fetchall()
                stats["total"] = len(rows)

                if not rows:
                    print(">>> No pending families for reset.")
                    return stats

                for family_no, anniv in rows:
                    errors = 0
                    try:
                        with transaction.atomic(using=self.audit_db):
                            # Reset sync flags
                            cursor.execute("UPDATE dbo.principal_applicant SET sync = NULL WHERE family_no = %s", [family_no])
                            cursor.execute("UPDATE dbo.member_info SET sync = NULL WHERE family_no = %s", [family_no])
                            cursor.execute("""
                                UPDATE dbo.member_anniversary
                                SET sync = NULL
                                WHERE member_no IN (
                                    SELECT member_no FROM dbo.member_info WHERE family_no = %s AND anniv = %s
                                )
                            """, [family_no, anniv])
                            cursor.execute("""
                                UPDATE dbo.member_benefits
                                SET sync = NULL
                                WHERE member_no IN (
                                    SELECT member_no FROM dbo.member_info WHERE family_no = %s AND anniv = %s
                                )
                            """, [family_no, anniv])

                    except Exception as e:
                        print(f"❌ Error resetting family {family_no}: {e}")
                        errors += 1

                    # Log each reset
                    MemberSyncResetLog.objects.create(
                        family_no=family_no,
                        anniv=anniv,
                        processed=(errors == 0),
                        errors=errors
                    )

                    if errors == 0:
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1

            print(f"✅ RESET DONE → Success: {stats['success']}, Failed: {stats['failed']}")
            return stats

        except Exception as e:
            print(f"❌ Critical error during member reset sync: {e}")
            return {"success": 0, "failed": 0, "total": 0}
        
        
        
        # engine/tasks/celery_tasks.py
# from celery import shared_task
# from .member_sync_reset import SmartMemberResetService

# @shared_task(bind=True, name="member_reset_sync_task")
# def member_reset_sync_task(self):
#     """
#     Celery task to reset member sync flags every 5 minutes.
#     """
#     service = SmartMemberResetService()
#     stats = service.run_member_reset_sync(batch_size=25)
#     return stats