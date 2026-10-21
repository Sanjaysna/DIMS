from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('', RedirectView.as_view(url='/dashboard/overview/', permanent=False)),
]
