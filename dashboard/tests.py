from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from inventory.models import Product, Rack, StockBatch
from orders.models import Order, OrderItem

User = get_user_model()


class DashboardPendingOrdersViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username='manager1',
            password='password123',
            is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username='regular_user',
            password='password123',
            is_staff=False
        )
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

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_non_staff_user_forbidden(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_get_pending_orders_page(self):
        self.client.force_login(self.manager)
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
        self.client.force_login(self.manager)
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
        self.staff_manager = User.objects.create_user(
            username='staff_manager',
            password='password123',
            is_staff=True
        )
        self.store = User.objects.create_user(
            username='downtown_store',
            password='password123',
            is_staff=False
        )
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

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_non_staff_user_forbidden(self):
        self.client.force_login(self.store)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_get_overview_page_success(self):
        self.client.force_login(self.staff_manager)
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


class InvoiceDownloadViewTests(TestCase):
    def setUp(self):
        self.staff_manager = User.objects.create_user(
            username='staff_downloader',
            password='password123',
            is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username='regular_customer',
            password='password123',
            is_staff=False
        )
        from decimal import Decimal
        from orders.models import Invoice, InvoiceItem, Order
        self.order = Order.objects.create(order_number='ORD-DL-01', status='billed', store=self.regular_user)
        self.invoice = Invoice.objects.create(order=self.order, invoice_total=Decimal('150.00'))
        self.product = Product.objects.create(sku='SKU-DL-01', name='Download Widget')
        self.item = InvoiceItem.objects.create(
            invoice=self.invoice,
            sku=self.product,
            unit_price=Decimal('150.00'),
            quantity=1,
            line_total=Decimal('150.00')
        )
        self.url = reverse('dashboard:invoice-download', kwargs={'id': self.invoice.id})

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_non_staff_user_forbidden(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_user_can_download_pdf(self):
        self.client.force_login(self.staff_manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(f'attachment; filename="invoice_{self.invoice.id}.pdf"', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_nonexistent_invoice_returns_404(self):
        self.client.force_login(self.staff_manager)
        url_404 = reverse('dashboard:invoice-download', kwargs={'id': 999999})
        response = self.client.get(url_404)
        self.assertEqual(response.status_code, 404)

