

import os
from celery import Celery
from datetime import timedelta

# --- Set Django settings module ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "healthcare_hub.settings")

# --- Create Celery app ---
app = Celery("healthcare_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.timezone = "Africa/Nairobi"
# healthcare_hub/celery.py

app.autodiscover_tasks(['intergration']) # Add the app name explicitly
app.autodiscover_tasks(['commisions']) # Add the app name explicitly



from celery.schedules import crontab
from datetime import timedelta




app.conf.beat_schedule = {
     "allocation-5pm-daily": {
        "task": "commissions.tasks.alloc_commissions_task",
        "schedule": crontab(hour=17, minute=0),
    },

    'smart-sync-every-2-minutes': {
        'task': 'tasks.run_full_smart_sync',
        'schedule': timedelta(seconds=120),  # every 2 minutes
    },
    
    'smart-sync-every-2-minutes': {
        'task': 'tasks.corp_copay_sync_task',
        'schedule': timedelta(seconds=120),  # every 2 minutes
    },

    # 'daily-allocation-5pm': {
    #     'task': 'tasks.daily_allocation_task',
    #     'schedule': crontab(hour=17, minute=0, day_of_week='1-6'),
    # },

    # -------------------------------------------------
    # Member Reset Sync Task every 2 minutes
    # -------------------------------------------------
    'member-reset-sync-every-2-minutes': {
        'task': 'tasks.member_reset_sync_task',
        'schedule': timedelta(seconds=120),  # every 2 minutes
    },
    "sync-debit-credit-every-minute": {
        "task":"etims.tasks.sync_debit_credit_notes_task",
        "schedule": 600.0,
    },

    # -------------------------
    # JOB 2: Send transactions
    # -------------------------
    "send-transactions-every-minute": {
        "task": "etims.tasks.send_pending_transactions_task",
        "schedule": 600.0,
    },

    # -------------------------
    # JOB 3: Sync KRA references
    # -------------------------
    "sync-kra-references-every-minute": {
        "task": "etims.tasks.sync_kra_references_task",
        "schedule": 600.0,
    },

}

