import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from inventory.models import Product, Rack, StockBatch, StockWriteoff
from inventory.services.slotting_algo import (
    NoAvailableRackError,
    assign_rack,
    calculate_abc_xyz,
)
from orders.models import Order, OrderItem

User = get_user_model()


class InventoryModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='wh_manager', password='password123')
        self.product = Product.objects.create(
            sku='SKU-1001',
            name='Industrial Motor',
            description='High torque electric motor',
            abc_class='A',
            xyz_class='X'
        )
        self.rack = Rack.objects.create(
            rack_id='AX-01',
            zone='AX',
            x_coord=10.0,
            y_coord=15.0,
            capacity=100
        )

    def test_product_creation(self):
        self.assertEqual(self.product.sku, 'SKU-1001')
        self.assertEqual(self.product.abc_class, 'A')
        self.assertEqual(self.product.xyz_class, 'X')

    def test_rack_occupancy_and_capacity(self):
        self.assertEqual(self.rack.current_occupancy, 0)
        self.assertEqual(self.rack.remaining_capacity, 100)

        StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-001',
            quantity=40,
            rack=self.rack
        )
        self.assertEqual(self.rack.current_occupancy, 40)
        self.assertEqual(self.rack.remaining_capacity, 60)

    def test_stock_batch_unique_together(self):
        StockBatch.objects.create(
            sku=self.product,
            batch_number='BATCH-001',
            quantity=10,
            rack=self.rack
        )
        with self.assertRaises(IntegrityError):
            StockBatch.objects.create(
                sku=self.product,
                batch_number='BATCH-001',
                quantity=20,
                rack=self.rack
            )

    def test_stock_writeoff_manager_override(self):
        writeoff = StockWriteoff.objects.create(
            product=self.product,
            quantity=5,
            reason='Damaged in transit',
            written_off_by=self.user
        )
        self.assertFalse(writeoff.is_revoked)
        self.assertIsNone(writeoff.revoked_by)
        self.assertIsNone(writeoff.revoked_at)

        # Manager override
        manager = User.objects.create_user(username='senior_manager', password='password123')
        now = timezone.now()
        writeoff.is_revoked = True
        writeoff.revoked_by = manager
        writeoff.revoked_at = now
        writeoff.save()

        refreshed = StockWriteoff.objects.get(pk=writeoff.pk)
        self.assertTrue(refreshed.is_revoked)
        self.assertEqual(refreshed.revoked_by, manager)
        self.assertIsNotNone(refreshed.revoked_at)


class SlottingAlgorithmTests(TestCase):
    def setUp(self):
        self.p_fast = Product.objects.create(sku='SKU-FAST', name='Fast Mover', abc_class='A', xyz_class='X')
        self.p_slow = Product.objects.create(sku='SKU-SLOW', name='Slow Mover', abc_class='C', xyz_class='Z')

        self.rack_ax = Rack.objects.create(rack_id='RACK-AX-01', zone='AX', capacity=50)
        self.rack_cz = Rack.objects.create(rack_id='RACK-CZ-01', zone='CZ', capacity=50)

    def test_bounded_6_month_abc_xyz_calculation(self):
        now = timezone.now()
        # Order within rolling 6 months (30 days ago)
        recent_order = Order.objects.create(order_number='ORD-RECENT', order_date=now - datetime.timedelta(days=30))
        OrderItem.objects.create(order=recent_order, product=self.p_fast, quantity=100, unit_price=Decimal('50.00'))

        # Old order older than 6 months (200 days ago) -> must be excluded from bounded calculation
        old_order = Order.objects.create(order_number='ORD-OLD', order_date=now - datetime.timedelta(days=200))
        OrderItem.objects.create(order=old_order, product=self.p_slow, quantity=1000, unit_price=Decimal('500.00'))

        res = calculate_abc_xyz(update_products=True)
        # Fast mover has all recent revenue -> Class A
        self.assertEqual(res['SKU-FAST']['abc_class'], 'A')
        # Slow mover had zero demand in the rolling 6-month window -> Class C, Class Z
        self.assertEqual(res['SKU-SLOW']['abc_class'], 'C')
        self.assertEqual(res['SKU-SLOW']['xyz_class'], 'Z')

    def test_rack_assignment_priority(self):
        # SKU-FAST (AX) should be assigned Tier 1 rack (RACK-AX-01)
        assigned_fast = assign_rack(self.p_fast, incoming_quantity=20)
        self.assertEqual(assigned_fast, 'RACK-AX-01')

        # SKU-SLOW (CZ) should be assigned Tier 4 rack (RACK-CZ-01)
        assigned_slow = assign_rack(self.p_slow, incoming_quantity=10)
        self.assertEqual(assigned_slow, 'RACK-CZ-01')

    def test_rack_capacity_exceeded(self):
        # Fill up RACK-AX-01 to capacity
        StockBatch.objects.create(sku=self.p_fast, batch_number='B-1', quantity=45, rack=self.rack_ax)
        # Asking for 10 units on RACK-AX-01 (capacity 50, remaining 5) will overflow to another rack
        assigned = assign_rack(self.p_fast, incoming_quantity=10)
        # RACK-AX-01 has only 5 units left, so it overflows to RACK-CZ-01
        self.assertEqual(assigned, 'RACK-CZ-01')

        # When all racks are full, raises NoAvailableRackError
        StockBatch.objects.create(sku=self.p_slow, batch_number='B-2', quantity=50, rack=self.rack_cz)
        with self.assertRaises(NoAvailableRackError):
            assign_rack(self.p_fast, incoming_quantity=10)
