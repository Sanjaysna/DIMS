from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from inventory.models import Product, Rack, StockBatch
from orders.models import Order, OrderItem

User = get_user_model()


class DashboardPendingOrdersViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='manager1', password='password123')
        self.product = Product.objects.create(sku='SKU-DASH-01', name='Dashboard Widget')
        self.rack = Rack.objects.create(rack_id='R-DASH-01', zone='AX', capacity=100)
        self.batch = StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-DASH-01',
            quantity=50,
            rack=self.rack
        )
        self.order = Order.objects.create(order_number='ORD-DASH-001', status='pending_approval')
        self.item = OrderItem.objects.create(order=self.order, product=self.product, quantity=10)
        self.url = reverse('dashboard:pending-orders')

    def test_get_pending_orders_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ORD-DASH-001')
        self.assertContains(response, 'SKU-DASH-01')
        self.assertTemplateUsed(response, 'dashboard/pending_orders.html')

    def test_post_approve_order_success(self):
        self.client.force_login(self.manager)
        response = self.client.post(self.url, {'order_id': self.order.id}, follow=True)
        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'approved')
        self.assertEqual(self.order.approved_by, self.manager)
        self.assertTrue(hasattr(self.order, 'pick_path'))
        self.assertContains(response, 'successfully approved')

    def test_post_approve_order_insufficient_stock(self):
        # Create order needing 200 units when only 50 exist
        big_order = Order.objects.create(order_number='ORD-BIG-001', status='pending_approval')
        OrderItem.objects.create(order=big_order, product=self.product, quantity=200)

        response = self.client.post(self.url, {'order_id': big_order.id}, follow=True)
        self.assertEqual(response.status_code, 200)

        big_order.refresh_from_db()
        self.assertEqual(big_order.status, 'pending_approval')
        self.assertContains(response, 'Allocation Failed')


class ManagerOverviewDashboardViewTests(TestCase):
    def setUp(self):
        self.store = User.objects.create_user(username='downtown_store', password='password123')
        self.prod = Product.objects.create(sku='SKU-OVERVIEW-01', name='Overview Widget', abc_class='A')
        self.rack = Rack.objects.create(rack_id='AX-OV-01', zone='AX', capacity=100)
        StockBatch.objects.create(sku=self.prod, batch_number='B-OV-01', quantity=75, rack=self.rack)

        # Create an order and invoice
        from decimal import Decimal
        from orders.models import Invoice, LedgerEntry
        self.order = Order.objects.create(order_number='ORD-OV-01', status='billed', store=self.store)
        self.invoice = Invoice.objects.create(order=self.order, invoice_total=Decimal('350.00'))
        LedgerEntry.objects.create(
            store=self.store,
            invoice=self.invoice,
            amount=Decimal('350.00'),
            type='charge',
            balance_after=Decimal('350.00')
        )
        self.url = reverse('dashboard:overview')

    def test_get_overview_page_success(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard/overview.html')

        # Check context keys
        self.assertIn('order_status_summary', response.context)
        self.assertIn('stock_abc_summary', response.context)
        self.assertIn('store_ledgers', response.context)
        self.assertEqual(response.context['total_orders'], 1)
        self.assertEqual(response.context['total_stock_units'], 75)

        # Check rendered content
        self.assertContains(response, 'downtown_store')
        self.assertContains(response, '350.00')
        self.assertContains(response, 'Order Fulfillment Pipeline')
        self.assertContains(response, 'Stock-On-Hand by ABC Velocity')

