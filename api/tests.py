from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from inventory.models import Product, Rack, Return, StockBatch, StockWriteoff
from orders.models import Order, OrderItem

User = get_user_model()


class AuthTokenAPITests(APITestCase):
    def setUp(self):
        self.username = 'warehouse_operator'
        self.password = 'secure_pass_123'
        self.user = User.objects.create_user(
            username=self.username,
            password=self.password
        )

    def test_obtain_token_pair_and_refresh(self):
        # 1. Obtain token pair
        token_url = '/api/token/'
        response = self.client.post(token_url, {
            'username': self.username,
            'password': self.password,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

        access_token = response.data['access']
        refresh_token = response.data['refresh']

        # 2. Refresh token
        refresh_url = '/api/token/refresh/'
        refresh_response = self.client.post(refresh_url, {
            'refresh': refresh_token,
        }, format='json')
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh_response.data)

        # 3. Use access token on protected endpoint
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        res = self.client.post('/api/v1/inventory/receive/', {}, format='json')
        # Should NOT be 401 (will be 400 bad request due to empty payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class StockReceiveAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='stock_receiver', password='password123')
        self.client.force_authenticate(user=self.user)
        self.url = '/api/v1/inventory/receive/'
        self.product = Product.objects.create(
            sku='SKU-VALVE-01',
            name='Hydraulic Valve',
            abc_class='A',
            xyz_class='X'
        )
        self.rack = Rack.objects.create(
            rack_id='AX-RACK-01',
            zone='AX',
            capacity=100
        )

    def test_unauthenticated_stock_receipt_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, data={}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_successful_stock_receipt(self):
        payload = {
            'sku': 'SKU-VALVE-01',
            'batch_number': 'BATCH-REC-100',
            'quantity': 25,
            'expiry_date': '2027-12-31',
            'source': 'fresh_receipt'
        }
        response = self.client.post(self.url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('stock_batch', response.data)
        self.assertIn('slotting_metadata', response.data)
        self.assertEqual(response.data['stock_batch']['rack_id'], 'AX-RACK-01')
        self.assertEqual(response.data['stock_batch']['abc_class_at_slotting'], 'A')
        self.assertEqual(response.data['stock_batch']['xyz_class_at_slotting'], 'X')

        # Verify record exists in DB
        batch = StockBatch.objects.get(sku=self.product, batch_number='BATCH-REC-100')
        self.assertEqual(batch.quantity, 25)
        self.assertEqual(batch.rack_id, 'AX-RACK-01')

    def test_duplicate_batch_rejection(self):
        StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-REC-100',
            quantity=10,
            rack=self.rack
        )
        payload = {
            'sku': 'SKU-VALVE-01',
            'batch_number': 'BATCH-REC-100',
            'quantity': 15,
        }
        response = self.client.post(self.url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('batch_number', response.data['errors'])

    def test_unknown_sku_rejection(self):
        payload = {
            'sku': 'NON-EXISTENT-SKU',
            'batch_number': 'BATCH-REC-999',
            'quantity': 10,
        }
        response = self.client.post(self.url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sku', response.data['errors'])

    def test_rack_capacity_exhausted_returns_409(self):
        # Fill rack to capacity
        StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-REC-FULL',
            quantity=100,
            rack=self.rack
        )
        payload = {
            'sku': 'SKU-VALVE-01',
            'batch_number': 'BATCH-REC-OVER',
            'quantity': 10,
        }
        response = self.client.post(self.url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('error', response.data)


class OrderPickPathAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pick_user', password='password123')
        self.client.force_authenticate(user=self.user)
        self.product = Product.objects.create(sku='SKU-VALVE-02', name='Ball Valve')
        self.rack = Rack.objects.create(rack_id='AY-01', zone='AY', x_coord=15.0, y_coord=25.0, capacity=100)
        self.batch = StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-VALVE-02',
            quantity=50,
            rack=self.rack
        )
        self.order = Order.objects.create(order_number='ORD-MOB-01', status='pending_approval')
        self.item = OrderItem.objects.create(order=self.order, product=self.product, quantity=5)

    def test_unauthenticated_pick_path_returns_401(self):
        self.client.force_authenticate(user=None)
        url = f"/api/v1/orders/{self.order.id}/pick-path/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pick_path_order_pending_approval_returns_400(self):
        url = f"/api/v1/orders/{self.order.id}/pick-path/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_pick_path_not_found_returns_404(self):
        url = "/api/v1/orders/NON-EXISTENT-ORDER/pick-path/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_pick_path_approved_order_returns_200(self):
        from orders.services.allocation_service import approve_and_allocate_order
        approve_and_allocate_order(self.order.id)

        url = f"/api/v1/orders/{self.order.id}/pick-path/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['order_number'], 'ORD-MOB-01')
        self.assertIn('total_distance', response.data)
        self.assertIn('baseline_distance', response.data)
        self.assertIn('steps', response.data)
        self.assertGreater(len(response.data['steps']), 0)
        step = response.data['steps'][0]
        self.assertEqual(step['rack_id'], 'AY-01')
        self.assertEqual(step['x_coord'], 15.0)
        self.assertEqual(step['y_coord'], 25.0)
        self.assertEqual(step['quantity_to_pick'], 5)


class ReturnCategorizeAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='returns_clerk_auth', password='password123')
        self.client.force_authenticate(user=self.user)
        self.product = Product.objects.create(
            sku='SKU-RETURN-01',
            name='Precision Gauge',
            abc_class='A',
            xyz_class='X'
        )
        self.rack = Rack.objects.create(
            rack_id='AX-RET-01',
            zone='AX',
            capacity=100
        )
        self.order = Order.objects.create(
            order_number='ORD-RET-TEST',
            status='delivered'
        )
        self.return_obj = Return.objects.create(
            order=self.order,
            sku=self.product,
            quantity=8,
            reason='Ordered wrong size',
            status='pending'
        )
        self.url = f"/api/v1/returns/{self.return_obj.id}/categorize/"

    def test_unauthenticated_return_categorize_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, data={'category': 'Reusable'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reusable_return_reslots_and_creates_stock_batch(self):
        response = self.client.post(self.url, data={'category': 'Reusable'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'processed')
        self.assertEqual(response.data['category'], 'Reusable')

        self.return_obj.refresh_from_db()
        self.assertEqual(self.return_obj.status, 'processed')
        self.assertEqual(self.return_obj.category, 'Reusable')

        # Verify a new StockBatch was created with source='return'
        batch = StockBatch.objects.filter(sku=self.product, source='return').first()
        self.assertIsNotNone(batch)
        self.assertEqual(batch.quantity, 8)
        self.assertEqual(batch.rack_id, 'AX-RET-01')

    def test_damaged_return_creates_stock_writeoff(self):
        ret_damaged = Return.objects.create(
            order=self.order,
            sku=self.product,
            quantity=3,
            reason='Dropped and shattered glass',
            status='pending'
        )
        url = f"/api/v1/returns/{ret_damaged.id}/categorize/"
        response = self.client.post(url, data={'category': 'Damaged'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ret_damaged.refresh_from_db()
        self.assertEqual(ret_damaged.status, 'processed')
        self.assertEqual(ret_damaged.category, 'Damaged')

        # Verify a StockWriteoff was created
        writeoff = StockWriteoff.objects.filter(product=self.product).first()
        self.assertIsNotNone(writeoff)
        self.assertEqual(writeoff.quantity, 3)
        self.assertIn('dropped and shattered glass', writeoff.reason.lower())

    def test_already_processed_return_rejection(self):
        self.return_obj.status = 'processed'
        self.return_obj.category = 'Reusable'
        self.return_obj.save()

        response = self.client.post(self.url, data={'category': 'Reusable'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)


class InventoryScanAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='scanner_user', password='password123')
        self.client.force_authenticate(user=self.user)
        self.url = '/api/v1/inventory/scan/'
        self.product = Product.objects.create(sku='SKU-SCAN-01', name='Scanner Sensor')
        self.rack = Rack.objects.create(rack_id='R-SCAN-01', zone='AX', capacity=100)
        self.batch = StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-SCAN-01',
            quantity=20,
            rack=self.rack
        )

    def test_unauthenticated_scan_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, data={'sku': 'SKU-SCAN-01', 'rack_id': 'R-SCAN-01'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_params_returns_400(self):
        response = self.client.post(self.url, data={'sku': 'SKU-SCAN-01'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_scan_returns_200_verified(self):
        response = self.client.post(self.url, data={'sku': 'SKU-SCAN-01', 'rack_id': 'R-SCAN-01'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get('status'), 'verified')

    def test_invalid_rack_returns_404(self):
        response = self.client.post(self.url, data={'sku': 'SKU-SCAN-01', 'rack_id': 'NON-EXISTENT-RACK'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_sku_returns_404(self):
        response = self.client.post(self.url, data={'sku': 'NON-EXISTENT-SKU', 'rack_id': 'R-SCAN-01'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

