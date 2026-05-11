from django.urls import path

from commisions.gx import CommissionFinancialView, CommissionFinancialViewPayable, CommissionFinancialViewPaid, CommissionPayUpdateView, CommissionRecordsView, DetailedCommissionRecordsView, AgentBrokersView
from .views import alloc_commissions  # make sure the import matches your file

urlpatterns = [
   
    path('alloc-commissions/', alloc_commissions, name='alloc_commissions'),
    path('records/', CommissionRecordsView.as_view(), name='commission-records'),
    path('detailed-records/', DetailedCommissionRecordsView.as_view(), name='detailed-commission-records'),
    path("debit-history/",CommissionFinancialView.as_view(),name="commission-financial"),
    path("pay/",CommissionFinancialViewPayable.as_view(),name="commission-financial"),
    path("paid/",CommissionFinancialViewPaid.as_view(),name="commission-financial-paid"),
    path("getagentbrokers/", AgentBrokersView.as_view(), name="get-agent-brokers"),
 
     path(
        "authorize/",
        CommissionPayUpdateView.as_view(),
        name="commission-pay-update"
    ),



]
