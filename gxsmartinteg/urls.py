from django.urls import path

from .views import BetterlifeMembersAPIView, GxSmartMemberSyncAPIView

urlpatterns = [
    path("members/", BetterlifeMembersAPIView.as_view(), name="betterlife-members"),
    path(
        "members/sync/<str:customers_code>/<int:policy_version>/",
        GxSmartMemberSyncAPIView.as_view(),
        name="gxsmart-member-sync-by-customer",
    ),
    path("members/sync/", GxSmartMemberSyncAPIView.as_view(), name="gxsmart-member-sync"),
]
