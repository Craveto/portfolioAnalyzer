from django.contrib import admin
from django.urls import include, path

from .root_views import favicon, index

urlpatterns = [
    path("", index, name="index"),
    path("favicon.ico", favicon, name="favicon"),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("api/analysis/", include("analysis.urls")),
]
