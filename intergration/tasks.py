from celery import shared_task
import logging

# Import the specific services
from intergration.Corporate.benefits import SmartBenefitSyncService
from intergration.Corporate.copay import  SmartRetailCopaySyncService
from intergration.Corporate.members import SmartMemberSyncService
from intergration.Corporate.restrictions import SmartProviderRestrictionSyncService
from intergration.Corporate.schemes import SmartSyncTaskService
from intergration.Corporate.categories import SmartCategorySyncTask
from intergration.Retail.benefits import SmartRetailBenefitSyncService
from intergration.Retail.categories import SmartRetailCategorySyncService
from intergration.Retail.members import SmartRetailMemberSyncService
from intergration.Retail.waitingperiods import SmartRetailWaitingPeriodSyncService


logger = logging.getLogger(__name__)

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

@shared_task(name="tasks.sync_copays_to_smart")
def sync_copays_task():
    logger.info("Task Started: sync_copays_to_smart")
    try:
        service = SmartRetailCopaySyncService()
        return service.run_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_copays_to_smart - {str(e)}")
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
    """
    Background task to sync Corporate Members 
    from MSSQL to SMART API via SmartMemberSyncService.
    """
    logger.info("Task Started: sync_members_to_smart")
    try:
        service = SmartMemberSyncService()
        return service.run_member_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_members_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}
    

@shared_task(name="tasks.sync_retail_copays_to_smart")
def sync_retail_copays_task():
    """
    Background task specifically for Retail Copay Synchronization
    with a 120s timeout constraint.
    """
    logger.info("Task Started: sync_retail_copays_to_smart")
    try:
        service = SmartRetailCopaySyncService()
        return service.run_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_retail_copays_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}
    
    
@shared_task(name="tasks.sync_provider_restrictions_to_smart")
def sync_provider_restrictions_task():
    """
    Background task to sync Scheme Provider Restrictions
    from MSSQL to SMART via SmartProviderRestrictionSyncService.
    """
    logger.info("Task Started: sync_provider_restrictions_to_smart")
    try:
        service = SmartProviderRestrictionSyncService()
        return service.run_restriction_sync()
    except Exception as e:
        logger.error(f"Task Failed: sync_provider_restrictions_to_smart - {str(e)}")
        return {"status": "error", "message": str(e)}
    
@shared_task(name="tasks.sync_provider_restrictions_to_smart")
def sync_provider_restrictions_task():
    """
    Background job to sync Provider Restrictions to SMART.
    """
    logger.info("Task Started: sync_provider_restrictions_to_smart")
    try:
        service = SmartProviderRestrictionSyncService()
        result = service.run_restriction_sync()
        logger.info(f"Task Completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Exception: {str(e)}")
        return {"status": "error", "message": str(e)}
    
    
@shared_task(name="tasks.sync_retail_benefits_to_smart")
def sync_retail_benefits_task(hais_token=None):
    """
    Background task to sync Retail Benefits from HAIS/MSSQL to SMART.
    """
    logger.info("Task Started: sync_retail_benefits_to_smart")
    
    # Optional: If token isn't passed, you might want to fetch a fresh one here
    # or rely on the service to handle its own specific auth if needed.
    
    try:
        service = SmartRetailBenefitSyncService()
        result = service.run_benefit_sync(hais_token)
        logger.info(f"Task Finished: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Failed: {str(e)}")
        return {"status": "error", "message": str(e)}
    
    
    
@shared_task(name="tasks.sync_retail_categories_to_smart")
def sync_retail_categories_task():
    """
    Celery task to sync Retail Categories to SMART API.
    Updates member_benefits and principal_applicant in MSSQL.
    """
    logger.info("Task Started: sync_retail_categories_to_smart")
    try:
        service = SmartRetailCategorySyncService()
        result = service.run_retail_category_sync()
        logger.info(f"Task Completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Exception: {str(e)}")
        return {"status": "error", "message": str(e)}
    
    
    
@shared_task(name="tasks.sync_retail_members_to_smart")
def sync_retail_members_task():
    """
    Celery task to sync Retail Members to SMART.
    Updates member_info, member_anniversary, and principal_applicant in MSSQL.
    """
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
    """
    Background task to sync benefit rules (waiting periods) to SMART.
    Targets member_benefits.wp_sync in MSSQL.
    """
    logger.info("Task Started: sync_retail_waiting_periods_to_smart")
    try:
        service = SmartRetailWaitingPeriodSyncService()
        result = service.run_retail_waiting_period_sync()
        logger.info(f"Task Completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Task Exception: {str(e)}")
        return {"status": "error", "message": str(e)}