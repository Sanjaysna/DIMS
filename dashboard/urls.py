from django.urls import path

from dashboard.views import ManagerOverviewDashboardView, PendingOrdersDashboardView

app_name = 'dashboard'

urlpatterns = [
    path('pending-orders/', PendingOrdersDashboardView.as_view(), name='pending-orders'),
    path('overview/', ManagerOverviewDashboardView.as_view(), name='overview'),
]

