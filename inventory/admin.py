from django.contrib import admin

from inventory.models import Product, Rack, Return, StockBatch, StockWriteoff


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'abc_class', 'xyz_class', 'created_at')
    search_fields = ('sku', 'name')
    list_filter = ('abc_class', 'xyz_class')


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ('rack_id', 'zone', 'capacity', 'current_occupancy', 'remaining_capacity', 'x_coord', 'y_coord')
    list_filter = ('zone',)
    search_fields = ('rack_id', 'zone')


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_number', 'sku', 'quantity', 'rack', 'source', 'abc_class_at_slotting', 'xyz_class_at_slotting', 'expiry_date')
    list_filter = ('source', 'abc_class_at_slotting', 'xyz_class_at_slotting')
    search_fields = ('batch_number', 'sku__sku', 'rack__rack_id')


@admin.register(StockWriteoff)
class StockWriteoffAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'quantity', 'written_off_by', 'is_revoked', 'revoked_by', 'revoked_at', 'created_at')
    list_filter = ('is_revoked', 'created_at')
    search_fields = ('product__sku', 'reason')


@admin.register(Return)
class ReturnAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'sku', 'quantity', 'category', 'status', 'created_at')
    list_filter = ('category', 'status', 'created_at')
    search_fields = ('order__order_number', 'sku__sku', 'reason')
