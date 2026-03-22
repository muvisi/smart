# # healthcare_hub/celery.py
# import os
# from celery import Celery
# from datetime import timedelta

# # --- Set Django settings module ---
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "healthcare_hub.settings")
# from celery.schedules import crontab
# # --- Create Celery app ---
# app = Celery("healthcare_hub")
# app.config_from_object("django.conf:settings", namespace="CELERY")
# app.autodiscover_tasks()


# app.conf.beat_schedule = {
   

     
# #    'daily-allocation': {
# #     'task': 'app.tasks.daily_allocation_task',
# #     'schedule': crontab(hour=17, minute=0, day_of_week='1-6'),
# # },
    
# }


# app.conf.timezone = "Africa/Nairobi"

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

# --- Task Schedule Configuration ---
# We use timedelta(seconds=60) for a strict 1-minute interval.
# We use 'countdown' in options to stagger execution within that minute.
app.conf.beat_schedule = {
    
    # --- PHASE 1: Foundations (Starts immediately at 0s) ---
    'sync-schemes-every-1-min': {
        'task': 'intergration.tasks.sync_schemes_to_smart',
        'schedule': timedelta(seconds=60),
    },
    'sync-categories-every-1-min': {
        'task': 'intergration.tasks.sync_categories_to_smart',
        'schedule': timedelta(seconds=60),
    },
    'sync-retail-categories-every-1-min': {
        'task': 'intergration.tasks.sync_retail_categories_to_smart',
        'schedule': timedelta(seconds=60),
    },

    # --- PHASE 2: Benefits (Starts at 15s offset) ---
    'sync-benefits-every-1-min': {
        'task': 'intergration.tasks.sync_benefits_to_smart',
        'schedule': timedelta(seconds=60),
        'options': {'countdown': 15}, 
    },
    'sync-retail-benefits-every-1-min': {
        'task': 'intergration.tasks.sync_retail_benefits_to_smart',
        'schedule': timedelta(seconds=60),
        'options': {'countdown': 15},
    },

    # --- PHASE 3: Members (Starts at 30s offset) ---
    'sync-members-every-1-min': {
        'task': 'intergration.tasks.sync_members_to_smart',
        'schedule': timedelta(seconds=60),
        'options': {'countdown': 30},
    },
    'sync-retail-members-every-1-min': {
        'task': 'intergration.tasks.sync_retail_members_to_smart',
        'schedule': timedelta(seconds=60),
        'options': {'countdown': 30},
    },

    # --- PHASE 4: Rules & Restrictions (Starts at 45s offset) ---
    'sync-waiting-periods-every-1-min': {
        'task': 'intergration.tasks.sync_retail_waiting_periods_to_smart',
        'schedule': timedelta(seconds=60),
        'options': {'countdown': 45},
    },
    'sync-retail-copays-every-1-min': {
        'task': 'intergration.tasks.sync_retail_copays_to_smart',
        'schedule': timedelta(seconds=60),
        'options': {'countdown': 45},
    },
    'sync-restrictions-every-1-min': {
        'task': 'intergration.tasks.sync_provider_restrictions_to_smart',
        'schedule': timedelta(seconds=60),
        'options': {'countdown': 45},
    },
}