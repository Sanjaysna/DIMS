import datetime
import threading
import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from inventory.models import Product, Rack, StockBatch
from orders.models import (
    Invoice,
    InvoiceItem,
    LedgerEntry,
    Order,
    OrderItem,
    OrderItemBatches,
    PickPath,
    PickPathStep,
)
from orders.services.allocation_service import (
    AllocationLockError,
    InsufficientStockError,
    approve_and_allocate_order,
)
from orders.services.billing_service import BillingError, BillingStateError, generate_invoice
from orders.services.picking_algo import generate_pick_path

User = get_user_model()



class PickingAlgorithmTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(sku='SKU-PROD-A', name='Component A')
        # Create racks with a zigzag/back-and-forth layout along the X-axis
        # FIFO visiting: (0,0) -> R1(10,0) -> R4(100,0) -> R2(20,0) -> R3(80,0) -> (0,0)
        # Baseline tour: (0,0)->(10,0) [10] -> (100,0) [90] -> (20,0) [80] -> (80,0) [60] -> (0,0) [80] = 320m
        # Optimized tour: (0,0)->(10,0)->(20,0)->(80,0)->(100,0)->(0,0) = 10 + 10 + 60 + 20 + 100 = 200m
        self.r1 = Rack.objects.create(rack_id='R-01', zone='AX', x_coord=10.0, y_coord=0.0, capacity=100)
        self.r2 = Rack.objects.create(rack_id='R-02', zone='AX', x_coord=20.0, y_coord=0.0, capacity=100)
        self.r3 = Rack.objects.create(rack_id='R-03', zone='AX', x_coord=80.0, y_coord=0.0, capacity=100)
        self.r4 = Rack.objects.create(rack_id='R-04', zone='AX', x_coord=100.0, y_coord=0.0, capacity=100)

        self.b1 = StockBatch.objects.create(sku=self.product, batch_number='B-01', quantity=50, rack=self.r1)
        self.b4 = StockBatch.objects.create(sku=self.product, batch_number='B-04', quantity=50, rack=self.r4)
        self.b2 = StockBatch.objects.create(sku=self.product, batch_number='B-02', quantity=50, rack=self.r2)
        self.b3 = StockBatch.objects.create(sku=self.product, batch_number='B-03', quantity=50, rack=self.r3)

        self.order = Order.objects.create(order_number='ORD-TSP-01', status='approved')
        self.item = OrderItem.objects.create(order=self.order, product=self.product, quantity=4)

        # Allocate batches in the zigzag order: R1, R4, R2, R3
        OrderItemBatches.objects.create(order_item=self.item, batch=self.b1, quantity_allocated=1)
        OrderItemBatches.objects.create(order_item=self.item, batch=self.b4, quantity_allocated=1)
        OrderItemBatches.objects.create(order_item=self.item, batch=self.b2, quantity_allocated=1)
        OrderItemBatches.objects.create(order_item=self.item, batch=self.b3, quantity_allocated=1)

    def test_nn_plus_2opt_beats_fifo_baseline(self):
        pick_path = generate_pick_path(self.order)

        self.assertIsNotNone(pick_path)
        self.assertGreater(pick_path.baseline_distance, pick_path.total_distance)

        # Verify steps count and ordered sequence
        steps = list(pick_path.steps.all().order_by('step_number'))
        self.assertEqual(len(steps), 4)

        # Ensure the sequence ordered racks by ascending X coordinates: R1 -> R2 -> R3 -> R4
        visited_rack_ids = [step.rack.rack_id for step in steps]
        self.assertEqual(visited_rack_ids, ['R-01', 'R-02', 'R-03', 'R-04'])


class FEFOAllocationTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='alloc_manager', password='password123')
        self.product = Product.objects.create(sku='SKU-MED-01', name='Pharma Reagent')
        self.rack = Rack.objects.create(rack_id='R-PHARMA-01', zone='AX', capacity=500)

        today = timezone.now().date()
        # Batch 1 expires first (in 10 days)
        self.batch_near = StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-EXP-10D',
            quantity=15,
            expiry_date=today + datetime.timedelta(days=10),
            rack=self.rack
        )
        # Batch 2 expires later (in 90 days)
        self.batch_far = StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-EXP-90D',
            quantity=50,
            expiry_date=today + datetime.timedelta(days=90),
            rack=self.rack
        )

        self.order = Order.objects.create(order_number='ORD-FEFO-01', status='pending_approval')
        self.item = OrderItem.objects.create(order=self.order, product=self.product, quantity=25)

    def test_fefo_allocation_depletes_earliest_expiry_first(self):
        approved_order = approve_and_allocate_order(self.order.id, approved_by=self.manager)

        self.assertEqual(approved_order.status, 'approved')
        self.assertEqual(approved_order.approved_by, self.manager)
        self.assertIsNotNone(approved_order.approved_at)

        # Batch 1 should be completely exhausted (15 -> 0)
        self.batch_near.refresh_from_db()
        self.assertEqual(self.batch_near.quantity, 0)

        # Batch 2 should be partially deducted (50 - 10 = 40)
        self.batch_far.refresh_from_db()
        self.assertEqual(self.batch_far.quantity, 40)

        # Verify allocations in OrderItemBatches
        allocations = list(OrderItemBatches.objects.filter(order_item=self.item).order_by('id'))
        self.assertEqual(len(allocations), 2)
        self.assertEqual(allocations[0].batch, self.batch_near)
        self.assertEqual(allocations[0].quantity_allocated, 15)
        self.assertEqual(allocations[1].batch, self.batch_far)
        self.assertEqual(allocations[1].quantity_allocated, 10)

        # Pick path should be generated
        self.assertTrue(has_PickPath := hasattr(approved_order, 'pick_path'))
        self.assertGreater(approved_order.pick_path.steps.count(), 0)

    def test_insufficient_stock_error(self):
        # Create an order asking for 500 units when only 65 are available
        order_oversized = Order.objects.create(order_number='ORD-FEFO-OVER', status='pending_approval')
        OrderItem.objects.create(order=order_oversized, product=self.product, quantity=500)

        with self.assertRaises(InsufficientStockError):
            approve_and_allocate_order(order_oversized.id, approved_by=self.manager)


class ConcurrencyLockTests(TransactionTestCase):
    """
    Tests non-blocking row locking (nowait=True) under simulated concurrent access.
    TransactionTestCase ensures real PostgreSQL transaction isolation across threads.
    """
    def setUp(self):
        self.product = Product.objects.create(sku='SKU-LOCK-TEST', name='Locked Widget')
        self.rack = Rack.objects.create(rack_id='R-LOCK-01', zone='AX', capacity=100)
        self.batch = StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-LOCKED',
            quantity=100,
            rack=self.rack
        )
        self.order = Order.objects.create(order_number='ORD-CONCUR-01', status='pending_approval')
        self.item = OrderItem.objects.create(order=self.order, product=self.product, quantity=10)

    def test_nowait_lock_raises_allocation_lock_error_when_held(self):
        lock_acquired = threading.Event()
        release_lock = threading.Event()
        lock_exception = []

        def hold_row_lock():
            from django.db import connection
            try:
                with connection.cursor() as cursor:
                    cursor.execute("BEGIN;")
                    cursor.execute(
                        "SELECT id FROM inventory_stockbatch WHERE id = %s FOR UPDATE;",
                        [self.batch.id]
                    )
                    lock_acquired.set()
                    # Keep holding lock until instructed
                    release_lock.wait(timeout=5)
                    cursor.execute("ROLLBACK;")
            except Exception as e:
                lock_exception.append(e)
            finally:
                connection.close()


        t = threading.Thread(target=hold_row_lock)
        t.daemon = True
        t.start()

        # Wait until background thread acquires the row lock
        self.assertTrue(lock_acquired.wait(timeout=3), "Background thread failed to acquire lock in time.")

        # Main thread attempts to allocate while lock is held
        # Must raise AllocationLockError immediately due to nowait=True
        with self.assertRaises(AllocationLockError):
            approve_and_allocate_order(self.order.id)

        # Release the lock and join thread
        release_lock.set()
        t.join(timeout=3)


class BillingServiceTests(TestCase):
    def setUp(self):
        self.store = User.objects.create_user(username='superstore_nyc', password='password123')
        self.prod1 = Product.objects.create(sku='SKU-BLL-01', name='Heavy Duty Drill')
        self.prod2 = Product.objects.create(sku='SKU-BLL-02', name='Drill Bit Set')
        self.order = Order.objects.create(
            order_number='ORD-BILL-001',
            status='packed',
            store=self.store
        )
        self.item1 = OrderItem.objects.create(
            order=self.order,
            product=self.prod1,
            quantity=2,
            unit_price=Decimal('150.00')
        )
        self.item2 = OrderItem.objects.create(
            order=self.order,
            product=self.prod2,
            quantity=4,
            unit_price=Decimal('25.50')
        )

    def test_generate_invoice_requires_packed_status(self):
        order_pending = Order.objects.create(
            order_number='ORD-NOT-PACKED',
            status='pending_approval'
        )
        OrderItem.objects.create(order=order_pending, product=self.prod1, quantity=1, unit_price=Decimal('10.00'))

        with self.assertRaises(BillingStateError):
            generate_invoice(order_pending.id)

    def test_generate_invoice_calculates_line_totals_and_billed_status(self):
        invoice = generate_invoice(self.order.id)

        # Expected: (2 * 150.00 = 300.00) + (4 * 25.50 = 102.00) = 402.00
        self.assertEqual(invoice.invoice_total, Decimal('402.00'))

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'billed')

        # Verify InvoiceItems created
        items = list(invoice.items.all().order_by('id'))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].line_total, Decimal('300.00'))
        self.assertEqual(items[1].line_total, Decimal('102.00'))

        # Verify running ledger entry for store
        ledger = LedgerEntry.objects.filter(store=self.store, invoice=invoice).first()
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.type, 'charge')
        self.assertEqual(ledger.amount, Decimal('402.00'))
        self.assertEqual(ledger.balance_after, Decimal('402.00'))

        # Second invoice for same store accumulates running balance
        order2 = Order.objects.create(
            order_number='ORD-BILL-002',
            status='packed',
            store=self.store
        )
        OrderItem.objects.create(order=order2, product=self.prod2, quantity=2, unit_price=Decimal('25.00'))
        invoice2 = generate_invoice(order2.id)
        self.assertEqual(invoice2.invoice_total, Decimal('50.00'))

        ledger2 = LedgerEntry.objects.filter(store=self.store, invoice=invoice2).first()
        self.assertEqual(ledger2.balance_after, Decimal('452.00'))


class ConcurrentBillingLedgerTests(TransactionTestCase):
    """
    Tests that multiple concurrent invoice generations for the SAME store
    maintain a strictly accurate running ledger balance without race conditions.
    """
    def setUp(self):
        self.store = User.objects.create_user(username='concur_store', password='password123')
        self.prod = Product.objects.create(sku='SKU-CONCUR-BILL', name='Concur Item')

    def test_concurrent_invoices_maintain_strictly_accurate_running_balance(self):
        # Create 4 packed orders for the same store, each for $100.00
        orders = []
        for i in range(1, 5):
            o = Order.objects.create(
                order_number=f'ORD-CONCUR-BILL-{i}',
                status='packed',
                store=self.store
            )
            OrderItem.objects.create(order=o, product=self.prod, quantity=1, unit_price=Decimal('100.00'))
            orders.append(o)

        threads = []
        errors = []

        def bill_order(order_id):
            from django.db import connection
            try:
                generate_invoice(order_id)
            except Exception as e:
                errors.append(e)
            finally:
                connection.close()


        for o in orders:
            t = threading.Thread(target=bill_order, args=(o.id,))
            threads.append(t)

        # Launch all billing transactions concurrently
        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Errors during concurrent billing: {errors}")

        # Verify all 4 orders were billed
        self.assertEqual(Order.objects.filter(order_number__startswith='ORD-CONCUR-BILL', status='billed').count(), 4)

        # Verify running ledger entries
        entries = list(LedgerEntry.objects.filter(store=self.store).order_by('id'))
        self.assertEqual(len(entries), 4)

        # Each entry amount is 100.00
        for entry in entries:
            self.assertEqual(entry.amount, Decimal('100.00'))
            self.assertEqual(entry.type, 'charge')

        # Final running balance must be exactly 400.00 with strictly incremental steps (100, 200, 300, 400)
        balances = [e.balance_after for e in entries]
        self.assertEqual(balances, [Decimal('100.00'), Decimal('200.00'), Decimal('300.00'), Decimal('400.00')])

