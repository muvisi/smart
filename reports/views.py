# from django.shortcuts import render

# # Create your views here.
# # report/views.py
# from rest_framework import generics, permissions
# from django_filters.rest_framework import DjangoFilterBackend
# from rest_framework.filters import SearchFilter, OrderingFilter

# from .models import *
# from .serializers import *

# # ------------------------------
# # Generic log ListView generator
# # ------------------------------
# class LogListView(generics.ListAPIView):
#     permission_classes = [permissions.IsAuthenticated]
#     filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
#     ordering = ['-created_at']

# # ------------------------------
# # Provider Restriction
# # ------------------------------
# class ProviderRestrictionSyncFailureListView(LogListView):
#     queryset = ProviderRestrictionSyncFailure.objects.all()
#     serializer_class = ProviderRestrictionSyncFailureSerializer
#     filterset_fields = ['corp_id', 'provider_code', 'status_code', 'user_id']
#     search_fields = ['corp_id', 'provider_code']

# class ProviderRestrictionSyncSuccessListView(LogListView):
#     queryset = ProviderRestrictionSyncSuccess.objects.all()
#     serializer_class = ProviderRestrictionSyncSuccessSerializer
#     filterset_fields = ['corp_id', 'provider_code', 'status_code', 'user_id']
#     search_fields = ['corp_id', 'provider_code']

# # ------------------------------
# # Waiting Period
# # ------------------------------
# class WaitingPeriodSyncFailureListView(LogListView):
#     queryset = WaitingPeriodSyncFailure.objects.all()
#     serializer_class = WaitingPeriodSyncFailureSerializer
#     filterset_fields = ['scheme_id', 'family_no', 'category', 'benefit', 'status_code']
#     search_fields = ['scheme_id', 'family_no', 'benefit']

# class WaitingPeriodSyncSuccessListView(LogListView):
#     queryset = WaitingPeriodSyncSuccess.objects.all()
#     serializer_class = WaitingPeriodSyncSuccessSerializer
#     filterset_fields = ['scheme_id', 'family_no', 'benefit', 'status_code']
#     search_fields = ['scheme_id', 'family_no', 'benefit']

# # ------------------------------
# # Hais Category
# # ------------------------------
# class HaisCategorySyncFailureListView(LogListView):
#     queryset = HaisCategorySyncFailure.objects.all()
#     serializer_class = HaisCategorySyncFailureSerializer
#     filterset_fields = ['corp_id', 'category_name', 'anniv', 'user_id', 'status_code']
#     search_fields = ['corp_id', 'category_name']

# class HaisCategorySyncSuccessListView(LogListView):
#     queryset = HaisCategorySyncSuccess.objects.all()
#     serializer_class = HaisCategorySyncSuccessSerializer
#     filterset_fields = ['corp_id', 'category_name', 'anniv', 'user_id', 'status_code']
#     search_fields = ['corp_id', 'category_name']

# # ------------------------------
# # Benefit
# # ------------------------------
# class BenefitSyncFailureListView(LogListView):
#     queryset = BenefitSyncFailure.objects.all()
#     serializer_class = BenefitSyncFailureSerializer
#     filterset_fields = ['corp_id', 'category', 'anniv', 'benefit_id', 'smart_status']
#     search_fields = ['corp_id', 'benefit_id', 'benefit_name']

# class BenefitSyncSuccessListView(LogListView):
#     queryset = BenefitSyncSuccess.objects.all()
#     serializer_class = BenefitSyncSuccessSerializer
#     filterset_fields = ['corp_id', 'category', 'anniv', 'benefit_id', 'smart_status']
#     search_fields = ['corp_id', 'benefit_id', 'benefit_name']

# # ------------------------------
# # Member
# # ------------------------------
# class MemberSyncFailureListView(LogListView):
#     queryset = MemberSyncFailure.objects.all()
#     serializer_class = MemberSyncFailureSerializer
#     filterset_fields = ['corp_id', 'category', 'anniv', 'smart_status']
#     search_fields = ['member_no', 'surname', 'family_no']

# class MemberSyncSuccessListView(LogListView):
#     queryset = MemberSyncSuccess.objects.all()
#     serializer_class = MemberSyncSuccessSerializer
#     filterset_fields = ['corp_id', 'category', 'anniv', 'smart_status']
#     search_fields = ['member_no', 'surname', 'family_no']

# # ------------------------------
# # API Sync Log
# # ------------------------------
# class ApiSyncLogListView(LogListView):
#     queryset = ApiSyncLog.objects.all()
#     serializer_class = ApiSyncLogSerializer
#     filterset_fields = ['api_name', 'transaction_name', 'status', 'http_code']
#     search_fields = ['api_name', 'transaction_name']

# # ------------------------------
# # Copay Log
# # ------------------------------
# class CopayLogListView(LogListView):
#     queryset = CopayLog.objects.all()
#     serializer_class = CopayLogSerializer
#     filterset_fields = ['transaction_name', 'status_code', 'status']
#     search_fields = ['transaction_name']
# # report/views.py
# from rest_framework import generics, permissions
# from django_filters.rest_framework import DjangoFilterBackend
# from rest_framework.filters import SearchFilter, OrderingFilter

# from .models import *
# from .serializers import *

# # ------------------------------
# # Generic log ListView generator
# # ------------------------------
# class LogListView(generics.ListAPIView):
#     permission_classes = [permissions.IsAuthenticated]
#     filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
#     ordering = ['-created_at']

# # ------------------------------
# # Provider Restriction
# # ------------------------------
# class ProviderRestrictionSyncFailureListView(LogListView):
#     queryset = ProviderRestrictionSyncFailure.objects.all()
#     serializer_class = ProviderRestrictionSyncFailureSerializer
#     filterset_fields = ['corp_id', 'provider_code', 'status_code', 'user_id']
#     search_fields = ['corp_id', 'provider_code']

# class ProviderRestrictionSyncSuccessListView(LogListView):
#     queryset = ProviderRestrictionSyncSuccess.objects.all()
#     serializer_class = ProviderRestrictionSyncSuccessSerializer
#     filterset_fields = ['corp_id', 'provider_code', 'status_code', 'user_id']
#     search_fields = ['corp_id', 'provider_code']

# # ------------------------------
# # Waiting Period
# # ------------------------------
# class WaitingPeriodSyncFailureListView(LogListView):
#     queryset = WaitingPeriodSyncFailure.objects.all()
#     serializer_class = WaitingPeriodSyncFailureSerializer
#     filterset_fields = ['scheme_id', 'family_no', 'category', 'benefit', 'status_code']
#     search_fields = ['scheme_id', 'family_no', 'benefit']

# class WaitingPeriodSyncSuccessListView(LogListView):
#     queryset = WaitingPeriodSyncSuccess.objects.all()
#     serializer_class = WaitingPeriodSyncSuccessSerializer
#     filterset_fields = ['scheme_id', 'family_no', 'benefit', 'status_code']
#     search_fields = ['scheme_id', 'family_no', 'benefit']

# # ------------------------------
# # Hais Category
# # ------------------------------
# class HaisCategorySyncFailureListView(LogListView):
#     queryset = HaisCategorySyncFailure.objects.all()
#     serializer_class = HaisCategorySyncFailureSerializer
#     filterset_fields = ['corp_id', 'category_name', 'anniv', 'user_id', 'status_code']
#     search_fields = ['corp_id', 'category_name']

# class HaisCategorySyncSuccessListView(LogListView):
#     queryset = HaisCategorySyncSuccess.objects.all()
#     serializer_class = HaisCategorySyncSuccessSerializer
#     filterset_fields = ['corp_id', 'category_name', 'anniv', 'user_id', 'status_code']
#     search_fields = ['corp_id', 'category_name']

# # ------------------------------
# # Benefit
# # ------------------------------
# class BenefitSyncFailureListView(LogListView):
#     queryset = BenefitSyncFailure.objects.all()
#     serializer_class = BenefitSyncFailureSerializer
#     filterset_fields = ['corp_id', 'category', 'anniv', 'benefit_id', 'smart_status']
#     search_fields = ['corp_id', 'benefit_id', 'benefit_name']

# class BenefitSyncSuccessListView(LogListView):
#     queryset = BenefitSyncSuccess.objects.all()
#     serializer_class = BenefitSyncSuccessSerializer
#     filterset_fields = ['corp_id', 'category', 'anniv', 'benefit_id', 'smart_status']
#     search_fields = ['corp_id', 'benefit_id', 'benefit_name']

# # ------------------------------
# # Member
# # ------------------------------
# class MemberSyncFailureListView(LogListView):
#     queryset = MemberSyncFailure.objects.all()
#     serializer_class = MemberSyncFailureSerializer
#     filterset_fields = ['corp_id', 'category', 'anniv', 'smart_status']
#     search_fields = ['member_no', 'surname', 'family_no']

# class MemberSyncSuccessListView(LogListView):
#     queryset = MemberSyncSuccess.objects.all()
#     serializer_class = MemberSyncSuccessSerializer
#     filterset_fields = ['corp_id', 'category', 'anniv', 'smart_status']
#     search_fields = ['member_no', 'surname', 'family_no']

# # ------------------------------
# # API Sync Log
# # ------------------------------
# class ApiSyncLogListView(LogListView):
#     queryset = ApiSyncLog.objects.all()
#     serializer_class = ApiSyncLogSerializer
#     filterset_fields = ['api_name', 'transaction_name', 'status', 'http_code']
#     search_fields = ['api_name', 'transaction_name']

# # ------------------------------
# # Copay Log
# # ------------------------------
# class CopayLogListView(LogListView):
#     queryset = CopayLog.objects.all()
#     serializer_class = CopayLogSerializer
#     filterset_fields = ['transaction_name', 'status_code', 'status']
#     search_fields = ['transaction_name']
# report/views.py
from rest_framework import generics, permissions
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import *
from .serializers import *

# ------------------------------
# Pagination class
# ------------------------------
class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

# ------------------------------
# Generic Log ListView generator
# ------------------------------
class LogListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering = ['-created_at']
    pagination_class = StandardPagination

# ------------------------------
# Filters
# ------------------------------
# Provider Restriction
class ProviderRestrictionSyncFailureFilter(FilterSet):
    class Meta:
        model = ProviderRestrictionSyncFailure
        fields = ['corp_id', 'provider_code', 'status_code', 'user_id']

class ProviderRestrictionSyncSuccessFilter(FilterSet):
    class Meta:
        model = ProviderRestrictionSyncSuccess
        fields = ['corp_id', 'provider_code', 'status_code', 'user_id']

# Waiting Period
class WaitingPeriodSyncFailureFilter(FilterSet):
    class Meta:
        model = WaitingPeriodSyncFailure
        fields = ['scheme_id', 'family_no', 'category', 'benefit', 'status_code']

class WaitingPeriodSyncSuccessFilter(FilterSet):
    class Meta:
        model = WaitingPeriodSyncSuccess
        fields = ['scheme_id', 'family_no', 'benefit', 'status_code']

# Hais Category
class HaisCategorySyncFailureFilter(FilterSet):
    class Meta:
        model = HaisCategorySyncFailure
        fields = ['corp_id', 'category_name', 'anniv', 'user_id', 'status_code']

class HaisCategorySyncSuccessFilter(FilterSet):
    class Meta:
        model = HaisCategorySyncSuccess
        fields = ['corp_id', 'category_name', 'anniv', 'user_id', 'status_code']

# Benefit
class BenefitSyncFailureFilter(FilterSet):
    class Meta:
        model = BenefitSyncFailure
        fields = ['corp_id', 'category', 'anniv', 'benefit_id', 'smart_status']

class BenefitSyncSuccessFilter(FilterSet):
    class Meta:
        model = BenefitSyncSuccess
        fields = ['corp_id', 'category', 'anniv', 'benefit_id', 'smart_status']

# Member
class MemberSyncFailureFilter(FilterSet):
    class Meta:
        model = MemberSyncFailure
        fields = ['corp_id', 'category', 'anniv', 'smart_status']

class MemberSyncSuccessFilter(FilterSet):
    class Meta:
        model = MemberSyncSuccess
        fields = ['corp_id', 'category', 'anniv', 'smart_status']

# API Sync Log
class ApiSyncLogFilter(FilterSet):
    class Meta:
        model = ApiSyncLog
        fields = ['api_name', 'transaction_name', 'status', 'http_code']

# Copay Log
# class CopayLogFilter(FilterSet):
#     class Meta:
#         model = CopayLog
#         fields = ['transaction_name', 'status_code', 'status']
# from django_filters.rest_framework import FilterSet
from engine.models import CopaySync  # or CopayLog if not renamed

class CopaySyncFilter(FilterSet):
    class Meta:
        model = CopaySync
        fields = ['transaction_name', 'status_code', 'status', 'corp_id']

# ------------------------------
# Views
# ------------------------------
# Provider Restriction
class ProviderRestrictionSyncFailureListView(LogListView):
    queryset = ProviderRestrictionSyncFailure.objects.all()
    serializer_class = ProviderRestrictionSyncFailureSerializer
    filterset_class = ProviderRestrictionSyncFailureFilter
    search_fields = ['corp_id', 'provider_code']

class ProviderRestrictionSyncSuccessListView(LogListView):
    queryset = ProviderRestrictionSyncSuccess.objects.all()
    serializer_class = ProviderRestrictionSyncSuccessSerializer
    filterset_class = ProviderRestrictionSyncSuccessFilter
    search_fields = ['corp_id', 'provider_code']

# Waiting Period
class WaitingPeriodSyncFailureListView(LogListView):
    queryset = WaitingPeriodSyncFailure.objects.all()
    serializer_class = WaitingPeriodSyncFailureSerializer
    filterset_class = WaitingPeriodSyncFailureFilter
    search_fields = ['scheme_id', 'family_no', 'benefit']

class WaitingPeriodSyncSuccessListView(LogListView):
    queryset = WaitingPeriodSyncSuccess.objects.all()
    serializer_class = WaitingPeriodSyncSuccessSerializer
    filterset_class = WaitingPeriodSyncSuccessFilter
    search_fields = ['scheme_id', 'family_no', 'benefit']

# Hais Category
class HaisCategorySyncFailureListView(LogListView):
    queryset = HaisCategorySyncFailure.objects.all()
    serializer_class = HaisCategorySyncFailureSerializer
    filterset_class = HaisCategorySyncFailureFilter
    search_fields = ['corp_id', 'category_name']

class HaisCategorySyncSuccessListView(LogListView):
    queryset = HaisCategorySyncSuccess.objects.all()
    serializer_class = HaisCategorySyncSuccessSerializer
    filterset_class = HaisCategorySyncSuccessFilter
    search_fields = ['corp_id', 'category_name']

# Benefit
class BenefitSyncFailureListView(LogListView):
    queryset = BenefitSyncFailure.objects.all()
    serializer_class = BenefitSyncFailureSerializer
    filterset_class = BenefitSyncFailureFilter
    search_fields = ['corp_id', 'benefit_id', 'benefit_name']

class BenefitSyncSuccessListView(LogListView):
    queryset = BenefitSyncSuccess.objects.all()
    serializer_class = BenefitSyncSuccessSerializer
    filterset_class = BenefitSyncSuccessFilter
    search_fields = ['corp_id', 'benefit_id', 'benefit_name']

# Member
class MemberSyncFailureListView(LogListView):
    queryset = MemberSyncFailure.objects.all()
    serializer_class = MemberSyncFailureSerializer
    filterset_class = MemberSyncFailureFilter
    search_fields = ['member_no', 'surname', 'family_no']

class MemberSyncSuccessListView(LogListView):
    queryset = MemberSyncSuccess.objects.all()
    serializer_class = MemberSyncSuccessSerializer
    filterset_class = MemberSyncSuccessFilter
    search_fields = ['member_no', 'surname', 'family_no']

# API Sync Log
class ApiSyncLogListView(LogListView):
    queryset = ApiSyncLog.objects.all()
    serializer_class = ApiSyncLogSerializer
    filterset_class = ApiSyncLogFilter
    search_fields = ['api_name', 'transaction_name']

# Copay Log
class CopayLogListView(LogListView):
    queryset = CopaySync.objects.all()
    serializer_class =  CopaySyncSerializer
    filterset_class = CopaySyncFilter
    search_fields = ['transaction_name']