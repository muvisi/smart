import os
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "healthcare_hub.settings")

app = Celery("healthcare_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")

app.conf.timezone = "Africa/Nairobi"

app.autodiscover_tasks([
    "intergration",
    "commisions",
    "etims",
])

app.conf.beat_schedule = {

    "smart-full-sync-every-10-minutes": {
        "task": "tasks.run_full_smart_sync",
        "schedule": timedelta(minutes=10),
    },

    # ETIMS jobs
    "sync-debit-credit-every-2-minutes": {
        "task": "etims.tasks.sync_debit_credit_notes_task",
        "schedule": timedelta(minutes=10),
    },

    "send-transactions-every-2-minutes": {
        "task": "etims.tasks.send_pending_transactions_task",
        "schedule": timedelta(minutes=10),
    },

    "sync-kra-references-every-2-minutes": {
        "task": "etims.tasks.sync_kra_references_task",
        "schedule": timedelta(minutes=10),
    },

    "etims-health-report-every-2-minutes": {
        "task": "etims.tasks.send_etims_health_report",
        "schedule": timedelta(hours=6),
    },
    "smart-full-sync-every-10-minutes": {
        "task": "tasks.run_full_smart_sync",
        "schedule": timedelta(minutes=10),
    }

    
}

app.conf.update(
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_track_started=True,
)