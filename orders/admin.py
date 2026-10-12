from django.contrib import admin

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


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class OrderItemBatchesInline(admin.TabularInline):
    model = OrderItemBatches
    extra = 0
    readonly_fields = ('batch', 'quantity_allocated', 'allocated_at')


class PickPathStepInline(admin.TabularInline):
    model = PickPathStep
    extra = 0
    readonly_fields = ('step_number', 'rack', 'batch', 'quantity_to_pick')


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    readonly_fields = ('sku', 'unit_price', 'quantity', 'line_total')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'status', 'store', 'order_date', 'approved_by', 'approved_at', 'created_at')
    list_filter = ('status', 'order_date')
    search_fields = ('order_number',)
    inlines = [OrderItemInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'product', 'quantity', 'unit_price')
    search_fields = ('order__order_number', 'product__sku')
    inlines = [OrderItemBatchesInline]


@admin.register(OrderItemBatches)
class OrderItemBatchesAdmin(admin.ModelAdmin):
    list_display = ('id', 'order_item', 'batch', 'quantity_allocated', 'allocated_at')
    search_fields = ('batch__batch_number', 'order_item__order__order_number')


@admin.register(PickPath)
class PickPathAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'total_distance', 'baseline_distance', 'created_at')
    inlines = [PickPathStepInline]


@admin.register(PickPathStep)
class PickPathStepAdmin(admin.ModelAdmin):
    list_display = ('id', 'pick_path', 'step_number', 'rack', 'batch', 'quantity_to_pick')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'invoice_total', 'created_at')
    search_fields = ('order__order_number',)
    inlines = [InvoiceItemInline]


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'invoice', 'sku', 'unit_price', 'quantity', 'line_total')
    search_fields = ('invoice__order__order_number', 'sku__sku')


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'store', 'invoice', 'type', 'amount', 'balance_after', 'created_at')
    list_filter = ('type', 'created_at')
    search_fields = ('store__username', 'invoice__order__order_number')
