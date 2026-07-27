from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("engine/", include("engine.urls")),
    path("api/account/", include("users.urls")),
    path("api/trigger/", include("trigger.urls")),
    path("api/report/", include("reports.urls")),
    path("api/commisions/", include("commisions.urls")),
    path("api/etims/", include("etims.urls")),
    path("api/gxsmartinteg/", include("gxsmartinteg.urls")),
    path("api/care-management/", include("care_management.urls")),
]
