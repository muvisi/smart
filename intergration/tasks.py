

from celery import shared_task, chain
import logging

from intergration.Corporate.benefits import SmartBenefitSyncService
from intergration.Corporate.copay import SmartRetailCopaySyncService
from intergration.Corporate.corpcopay import SmartCorpCopaySyncService
from intergration.Corporate.members import SmartMemberSyncService
from intergration.Corporate.restrictions import SmartProviderRestrictionSyncService
from intergration.Corporate.schemes import SmartSyncTaskService
from intergration.Corporate.categories import SmartCategorySyncTask

from intergration.Retail.benefits import SmartRetailBenefitSyncService
from intergration.Retail.categories import SmartRetailCategorySyncService
from intergration.Retail.members import SmartRetailMemberSyncService
from intergration.Retail.waitingperiods import SmartRetailWaitingPeriodSyncService
from intergration.recon import SmartMemberResetService


logger = logging.getLogger(__name__)


# -----------------------------
# CORPORATE TASKS
# -----------------------------
@shared_task(bind=True,name="tasks.member_reset_sync_task")
def member_reset_sync_task(self):
    """
    Celery task to reset member sync flags every 5 minutes.
    """
    service = SmartMemberResetService()
    stats = service.run_member_reset_sync(batch_size=25)
    return stats


@shared_task(name="tasks.sync_schemes_to_smart")
def sync_schemes_task():
    logger.info("Task Started: sync_schemes_to_smart")
    try:
        service = SmartSyncTaskService()
        return service.run_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_schemes_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_categories_to_smart")
def sync_categories_task():
    logger.info("Task Started: sync_categories_to_smart")
    try:
        service = SmartCategorySyncTask()
        return service.run_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_categories_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_benefits_to_smart")
def sync_benefits_task():
    logger.info("Task Started: sync_benefits_to_smart")
    try:
        service = SmartBenefitSyncService()
        return service.run_benefit_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_benefits_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_members_to_smart")
def sync_members_task():
    logger.info("Task Started: sync_members_to_smart")
    try:
        service = SmartMemberSyncService()
        return service.run_member_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_members_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


# -----------------------------
# RETAIL TASKS
# -----------------------------

@shared_task(name="tasks.sync_retail_categories_to_smart")
def sync_retail_categories_task():
    logger.info("Task Started: sync_retail_categories_to_smart")
    try:
        service = SmartRetailCategorySyncService()
        result = service.run_retail_category_sync()
        logger.info(f"Task Completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Exception: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_retail_benefits_to_smart")
def sync_retail_benefits_task(hais_token=None):
    logger.info("Task Started: sync_retail_benefits_to_smart")
    try:
        service = SmartRetailBenefitSyncService()
        result = service.run_benefit_sync(hais_token)
        logger.info(f"Task Finished: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Failed: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_retail_members_to_smart")
def sync_retail_members_task():
    logger.info("Task Started: sync_retail_members_to_smart")
    try:
        service = SmartRetailMemberSyncService()
        result = service.run_retail_member_sync()
        logger.info(f"Task Completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Exception: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_retail_waiting_periods_to_smart")
def sync_retail_waiting_periods_task():
    logger.info("Task Started: sync_retail_waiting_periods_to_smart")
    try:
        service = SmartRetailWaitingPeriodSyncService()
        result = service.run_retail_waiting_period_sync()
        logger.info(f"Task Completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Exception: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_retail_copays_to_smart")
def sync_retail_copays_task():
    logger.info("Task Started: sync_retail_copays_to_smart")
    try:
        service = SmartRetailCopaySyncService()
        return service.run_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_retail_copays_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_provider_restrictions_to_smart")
def sync_provider_restrictions_task():
    logger.info("Task Started: sync_provider_restrictions_to_smart")
    try:
        service = SmartProviderRestrictionSyncService()
        result = service.run_restriction_sync()
        logger.info(f"Task Completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Exception: {str(e)}")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------
# MASTER ORCHESTRATION TASK (SEQUENTIAL PIPELINE)
# ---------------------------------------------------
@shared_task(bind=True, name="tasks.corp_copay_sync_task")
def corp_copay_sync_task(self):
    """
    Celery task to sync corporate copays to SMART.
    Runs in batches from MSSQL → SMART → updates sync status + logs.
    """
    try:
        service = SmartCorpCopaySyncService()
        stats = service.run_sync()

        logger.info(f"✅ Corp Copay Sync Task Completed: {stats}")
        return stats

    except Exception as e:
        logger.error(f"❌ Corp Copay Sync Task Failed: {e}")
        raise
@shared_task(name="tasks.run_full_smart_sync")
def run_full_smart_sync():
    """
    Master sync pipeline ensuring correct dependency order.
    """

    logger.info("Starting FULL SMART Sync Pipeline")

    workflow = chain(

        # Phase 1: Foundations
        sync_schemes_task.s(),

        # Phase 2: Categories
        sync_categories_task.s(),
        sync_retail_categories_task.s(),

        # Phase 3: Benefits
        sync_benefits_task.s(),
        sync_retail_benefits_task.s(),
        # corp_copay_sync_task.s(),

        # Phase 4: Members
        sync_members_task.s(),
        sync_retail_members_task.s(),

        # Phase 5: Rules / Restrictions
        sync_retail_waiting_periods_task.s(),
        sync_retail_copays_task.s(),
        sync_provider_restrictions_task.s(),

    )

    workflow.apply_async()

    return {"status": "pipeline_started"}

