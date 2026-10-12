from django.conf import settings
from django.db import models


class Product(models.Model):
    ABC_CHOICES = [
        ('A', 'Class A - High Value / Fast Moving'),
        ('B', 'Class B - Moderate Value / Medium Velocity'),
        ('C', 'Class C - Low Value / Slow Moving'),
    ]

    XYZ_CHOICES = [
        ('X', 'Class X - Steady / High Predictability'),
        ('Y', 'Class Y - Variable / Moderate Predictability'),
        ('Z', 'Class Z - Sporadic / Low Predictability'),
    ]

    sku = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    abc_class = models.CharField(max_length=1, choices=ABC_CHOICES, blank=True, null=True, db_index=True)
    xyz_class = models.CharField(max_length=1, choices=XYZ_CHOICES, blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sku']

    def __str__(self):
        return f"{self.sku} - {self.name}"


class Rack(models.Model):
    rack_id = models.CharField(max_length=32, primary_key=True)
    zone = models.CharField(max_length=16, db_index=True)
    x_coord = models.FloatField(default=0.0)
    y_coord = models.FloatField(default=0.0)
    capacity = models.PositiveIntegerField()

    class Meta:
        ordering = ['zone', 'rack_id']

    def __str__(self):
        return f"Rack {self.rack_id} (Zone {self.zone}, Cap: {self.capacity})"

    @property
    def current_occupancy(self):
        total = self.stock_batches.aggregate(total_qty=models.Sum('quantity'))['total_qty']
        return total or 0

    @property
    def remaining_capacity(self):
        return max(0, self.capacity - self.current_occupancy)


class StockBatch(models.Model):
    sku = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_batches', db_column='sku')
    batch_number = models.CharField(max_length=64)
    quantity = models.PositiveIntegerField()
    expiry_date = models.DateField(null=True, blank=True)
    rack = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name='stock_batches')
    source = models.CharField(max_length=64, default='fresh_receipt')
    abc_class_at_slotting = models.CharField(max_length=1, blank=True, null=True)
    xyz_class_at_slotting = models.CharField(max_length=1, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('sku', 'batch_number'),)
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch {self.batch_number} - SKU: {self.sku_id} (Qty: {self.quantity}, Rack: {self.rack_id})"


class StockWriteoff(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='writeoffs')
    quantity = models.PositiveIntegerField()
    reason = models.TextField(blank=True, default='')
    written_off_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='written_off_records'
    )
    is_revoked = models.BooleanField(default=False)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revoked_writeoff_records'
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "REVOKED" if self.is_revoked else "ACTIVE"
        return f"Writeoff #{self.pk} - {self.product_id} ({self.quantity} units) [{status}]"


class Return(models.Model):
    """
    Tracks customer returns for inspection and re-slotting or write-off.
    """
    CATEGORY_CHOICES = [
        ('Reusable', 'Reusable'),
        ('Damaged', 'Damaged'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending Inspection'),
        ('processed', 'Processed'),
    ]

    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='returns')
    sku = models.ForeignKey(Product, on_delete=models.CASCADE, db_column='sku', related_name='returns')
    quantity = models.PositiveIntegerField()
    reason = models.TextField(blank=True, default='')
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        null=True,
        blank=True,
        default=None
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Return #{self.pk} - Order {self.order.order_number} (SKU: {self.sku_id}, Qty: {self.quantity}, Status: {self.status})"

