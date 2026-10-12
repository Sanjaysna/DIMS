from django.urls import path

from api.views import (
    OrderPickPathAPIView,
    ReturnCategorizeAPIView,
    StockReceiveAPIView,
)

app_name = 'api'

urlpatterns = [
    path('v1/inventory/receive/', StockReceiveAPIView.as_view(), name='stock-receive'),
    path('v1/orders/<str:order_id>/pick-path/', OrderPickPathAPIView.as_view(), name='order-pick-path'),
    path('v1/returns/<str:return_id>/categorize/', ReturnCategorizeAPIView.as_view(), name='return-categorize'),
]


