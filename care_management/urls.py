from django.urls import path

from .views import DeclineReportAPIView, FollowUpReportAPIView, LouStatusReportAPIView, LouStatusReportDownloadAPIView

urlpatterns = [
    path("lou-status-report/download/<str:filename>", LouStatusReportDownloadAPIView.as_view(), name="lou-status-report-download"),
    path("lou-status-report/download/<str:filename>/", LouStatusReportDownloadAPIView.as_view(), name="lou-status-report-download-slash"),
    path("decline-report", DeclineReportAPIView.as_view(), name="decline-report"),
    path("decline-report/", DeclineReportAPIView.as_view(), name="decline-report-slash"),
    path("follow-up-report", FollowUpReportAPIView.as_view(), name="follow-up-report"),
    path("follow-up-report/", FollowUpReportAPIView.as_view(), name="follow-up-report-slash"),
    path("lou-status-report", LouStatusReportAPIView.as_view(), name="lou-status-report"),
    path("lou-status-report/", LouStatusReportAPIView.as_view(), name="lou-status-report-slash"),
]
