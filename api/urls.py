from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from api.views import (
    InventoryScanAPIView,
    OrderListCreateAPIView,
    OrderPickPathAPIView,
    ProductListAPIView,
    ReturnCategorizeAPIView,
    StockReceiveAPIView,
)

app_name = 'api'

urlpatterns = [
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('v1/products/', ProductListAPIView.as_view(), name='product-list'),
    path('v1/orders/', OrderListCreateAPIView.as_view(), name='order-list-create'),
    path('v1/inventory/receive/', StockReceiveAPIView.as_view(), name='stock-receive'),
    path('v1/inventory/scan/', InventoryScanAPIView.as_view(), name='inventory-scan'),
    path('v1/orders/<str:order_id>/pick-path/', OrderPickPathAPIView.as_view(), name='order-pick-path'),
    path('v1/returns/<str:return_id>/categorize/', ReturnCategorizeAPIView.as_view(), name='return-categorize'),
]
