from django.urls import path

from etims.debits import DebitCreditListAPIView, sync_debit_credit_notes
from etims.pull_etims import get_next_kra_reference
from etims.push_etims import send_next_transaction
# from .views import sync_debit_credit_notes

urlpatterns = [
    path("sync-debit-credit-notes/",sync_debit_credit_notes,name="sync-debit-credit-notes"),
    path("debit-credit/", DebitCreditListAPIView.as_view(), name="debit-credit-list"),
    path("etims/send/", send_next_transaction, name="send_next_transaction"),
    path("etims/kra-reference/", get_next_kra_reference, name="get_next_kra_reference"),

]