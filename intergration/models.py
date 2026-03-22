from django.db import models

# Create your models here.

import uuid
from django.db import models

class CopaySyncSuccess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    corp_id = models.CharField(max_length=50)
    category = models.CharField(max_length=100)
    benefit = models.CharField(max_length=100)
    provider = models.CharField(max_length=100)
    service = models.CharField(max_length=100)
    copay_amount = models.FloatField()
    request_object = models.JSONField()
    smart_status = models.IntegerField()
    smart_response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

class CopaySyncFailure(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    corp_id = models.CharField(max_length=50)
    category = models.CharField(max_length=100)
    benefit = models.CharField(max_length=100)
    provider = models.CharField(max_length=100)
    service = models.CharField(max_length=100)
    copay_amount = models.FloatField()
    request_object = models.JSONField()
    smart_status = models.IntegerField()
    smart_response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    
    
    import uuid
from django.db import models

class CopaySyncSuccess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Supporting both Corporate and Retail IDs
    corp_id = models.CharField(max_length=50, null=True, blank=True)
    retail_id = models.CharField(max_length=50, null=True, blank=True)
    
    category = models.CharField(max_length=100)
    benefit = models.CharField(max_length=100)
    provider = models.CharField(max_length=100)
    service = models.CharField(max_length=100)
    
    # Decimal is better for currency (KES) than Float
    copay_amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Postgres JSONB fields
    request_object = models.JSONField()
    smart_status = models.IntegerField()
    smart_response = models.JSONField()
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'copay_sync_success'
        verbose_name_plural = "Copay Sync Successes"


class CopaySyncFailure(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Supporting both Corporate and Retail IDs
    corp_id = models.CharField(max_length=50, null=True, blank=True)
    retail_id = models.CharField(max_length=50, null=True, blank=True)
    
    category = models.CharField(max_length=100)
    benefit = models.CharField(max_length=100)
    provider = models.CharField(max_length=100)
    service = models.CharField(max_length=100)
    
    copay_amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    request_object = models.JSONField()
    smart_status = models.IntegerField()
    smart_response = models.JSONField()
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'copay_sync_failure'
        verbose_name_plural = "Copay Sync Failures"