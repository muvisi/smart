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

@shared_task(bind=True, name="tasks.member_reset_sync_task")
def member_reset_sync_task(self):
    service = SmartMemberResetService()
    return service.run_member_reset_sync(batch_size=25)


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


@shared_task(bind=True, name="tasks.corp_copay_sync_task")
def corp_copay_sync_task(self):
    logger.info("Task Started: corp_copay_sync_task")
    try:
        service = SmartCorpCopaySyncService()
        return service.run_sync()
    except Exception as e:
        logger.error(f"Task Failed: corp_copay_sync_task - {str(e)}")
        raise


@shared_task(name="tasks.sync_provider_restrictions_to_smart")
def sync_provider_restrictions_task():
    logger.info("Task Started: sync_provider_restrictions_to_smart")
    try:
        service = SmartProviderRestrictionSyncService()
        return service.run_restriction_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_provider_restrictions_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


# -----------------------------
# RETAIL TASKS
# -----------------------------

@shared_task(name="tasks.sync_retail_categories_to_smart")
def sync_retail_categories_task():
    logger.info("Task Started: sync_retail_categories_to_smart")
    try:
        service = SmartRetailCategorySyncService()
        return service.run_retail_category_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_retail_categories_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_retail_benefits_to_smart")
def sync_retail_benefits_task():
    logger.info("Task Started: sync_retail_benefits_to_smart")
    try:
        service = SmartRetailBenefitSyncService()
        return service.run_benefit_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_retail_benefits_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_retail_members_to_smart")
def sync_retail_members_task():
    logger.info("Task Started: sync_retail_members_to_smart")
    try:
        service = SmartRetailMemberSyncService()
        return service.run_retail_member_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_retail_members_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task(name="tasks.sync_retail_waiting_periods_to_smart")
def sync_retail_waiting_periods_task():
    logger.info("Task Started: sync_retail_waiting_periods_to_smart")
    try:
        service = SmartRetailWaitingPeriodSyncService()
        return service.run_retail_waiting_period_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_retail_waiting_periods_to_smart - {str(e)}")
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


# ---------------------------------------------------
# MASTER ORCHESTRATION TASK
# ---------------------------------------------------

@shared_task(name="tasks.run_full_smart_sync")
def run_full_smart_sync():
    logger.info("Starting FULL SMART Sync Pipeline")

    workflow = chain(
        # 1. Reset sync flags first
        member_reset_sync_task.si(),

        # 2. Foundations
        sync_schemes_task.si(),

        # 3. Categories
        sync_categories_task.si(),
        sync_retail_categories_task.si(),

        # 4. Benefits
        sync_benefits_task.si(),
        sync_retail_benefits_task.si(),

        # 5. Copays
        corp_copay_sync_task.si(),
        sync_retail_copays_task.si(),

        # 6. Members
        sync_members_task.si(),
        sync_retail_members_task.si(),

        # 7. Rules / Restrictions
        sync_retail_waiting_periods_task.si(),
        sync_provider_restrictions_task.si(),
    )

    result = workflow.apply_async()

    return {
        "status": "pipeline_started",
        "chain_id": result.id,
    }