from rest_framework import status
from rest_framework.test import APITestCase

from inventory.models import Product, Rack, Return, StockBatch, StockWriteoff
from orders.models import Order, OrderItem




class StockReceiveAPITests(APITestCase):
    def setUp(self):
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


