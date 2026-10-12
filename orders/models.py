from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone



class Order(models.Model):
    STATUS_CHOICES = [
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('packing', 'Packing'),
        ('packed', 'Packed'),
        ('billed', 'Billed'),
        ('dispatched', 'Dispatched'),
        ('delivered', 'Delivered'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    order_number = models.CharField(max_length=64, unique=True, db_index=True)
    order_date = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default='pending_approval',
        db_index=True
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_orders'
    )
    store = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store_orders'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-order_date']


    def __str__(self):
        return f"Order {self.order_number} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE, related_name='order_items')
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        indexes = [
            models.Index(fields=['product', 'order']),
        ]

    def __str__(self):
        return f"{self.product_id} x {self.quantity} in Order {self.order_id}"


class OrderItemBatches(models.Model):
    """
    Fulfillment mapping model linking OrderItem to specific StockBatch instances
    using First-Expiry-First-Out (FEFO) allocation.
    """
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='allocated_batches')
    batch = models.ForeignKey('inventory.StockBatch', on_delete=models.PROTECT, related_name='order_allocations')
    quantity_allocated = models.PositiveIntegerField()
    allocated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Order Item Batch Allocation'
        verbose_name_plural = 'Order Item Batch Allocations'

    def __str__(self):
        return f"Allocated {self.quantity_allocated} of Batch {self.batch.batch_number} to {self.order_item}"


class PickPath(models.Model):
    """
    Stores calculated pick path metadata comparing baseline FIFO distance vs
    the optimized Nearest-Neighbour + 2-opt tour distance.
    """
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='pick_path')
    total_distance = models.FloatField(help_text="Optimized tour distance (NN + 2-opt)")
    baseline_distance = models.FloatField(help_text="Baseline tour distance (FIFO order sequence)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PickPath for {self.order.order_number} (Opt: {self.total_distance:.2f}m, Base: {self.baseline_distance:.2f}m)"


class PickPathStep(models.Model):
    """
    Individual sequential waypoint/pick action along an optimized PickPath.
    """
    pick_path = models.ForeignKey(PickPath, on_delete=models.CASCADE, related_name='steps')
    step_number = models.PositiveIntegerField()
    rack = models.ForeignKey('inventory.Rack', on_delete=models.PROTECT, related_name='pick_steps')
    batch = models.ForeignKey('inventory.StockBatch', on_delete=models.PROTECT, related_name='pick_steps')
    quantity_to_pick = models.PositiveIntegerField()

    class Meta:
        ordering = ['step_number']
        unique_together = (('pick_path', 'step_number'),)

    def __str__(self):
        return f"Step {self.step_number}: Pick {self.quantity_to_pick} of Batch {self.batch.batch_number} at Rack {self.rack_id}"


class Invoice(models.Model):
    """
    Financial billing record for a packed order.
    """
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice')
    invoice_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Sum of line items at the time of invoice generation"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice for Order #{self.order.order_number} (${self.invoice_total})"


class InvoiceItem(models.Model):
    """
    Line item snapshot on an invoice capturing final billed unit price.
    """
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    sku = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='invoice_items')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Unit price captured at billing time")
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        indexes = [
            models.Index(fields=['invoice', 'sku']),
        ]

    def __str__(self):
        return f"{self.sku_id} x {self.quantity} = ${self.line_total} (Invoice #{self.invoice_id})"


class LedgerEntry(models.Model):
    """
    Financial running ledger tracking accounts receivable balances for stores/customers.
    """
    TYPE_CHOICES = [
        ('charge', 'Charge / Debit'),
        ('payment', 'Payment / Credit'),
    ]

    store = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ledger_entries'
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entries'
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['store', '-created_at']),
        ]

    def __str__(self):
        return f"LedgerEntry #{self.pk} - Store {self.store_id} [{self.type} ${self.amount}] Balance: ${self.balance_after}"

