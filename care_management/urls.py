from django.urls import path

from .views import LouStatusReportAPIView, LouStatusReportDownloadAPIView

urlpatterns = [
    path("lou-status-report/download/<str:filename>", LouStatusReportDownloadAPIView.as_view(), name="lou-status-report-download"),
    path("lou-status-report/download/<str:filename>/", LouStatusReportDownloadAPIView.as_view(), name="lou-status-report-download-slash"),
    path("lou-status-report", LouStatusReportAPIView.as_view(), name="lou-status-report"),
    path("lou-status-report/", LouStatusReportAPIView.as_view(), name="lou-status-report-slash"),
]
