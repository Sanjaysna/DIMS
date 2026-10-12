from rest_framework import serializers

from inventory.models import Product, Rack, StockBatch


class StockBatchReceiveSerializer(serializers.Serializer):
    """
    Validates the incoming stock receipt payload for the Put-away phase.
    """
    sku = serializers.CharField(max_length=64, required=True)
    batch_number = serializers.CharField(max_length=64, required=True)
    quantity = serializers.IntegerField(min_value=1, required=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    source = serializers.CharField(max_length=64, required=False, default='fresh_receipt')

    def validate_sku(self, value):
        sku_clean = value.strip()
        if not Product.objects.filter(sku=sku_clean).exists():
            raise serializers.ValidationError(
                f"Product with SKU '{sku_clean}' does not exist. Please register the product before receiving stock."
            )
        return sku_clean

    def validate(self, attrs):
        sku = attrs.get('sku')
        batch_number = attrs.get('batch_number')
        if StockBatch.objects.filter(sku_id=sku, batch_number=batch_number).exists():
            raise serializers.ValidationError({
                "batch_number": f"Batch '{batch_number}' for SKU '{sku}' already exists."
            })
        return attrs


class StockBatchOutputSerializer(serializers.ModelSerializer):
    """
    Serializes created StockBatch records.
    """
    rack_id = serializers.CharField(source='rack.rack_id', read_only=True)
    rack_zone = serializers.CharField(source='rack.zone', read_only=True)
    sku = serializers.CharField(source='sku_id', read_only=True)

    class Meta:
        model = StockBatch
        fields = [
            'id',
            'sku',
            'batch_number',
            'quantity',
            'expiry_date',
            'rack_id',
            'rack_zone',
            'source',
            'abc_class_at_slotting',
            'xyz_class_at_slotting',
            'created_at',
            'updated_at',
        ]


class PickPathStepSerializer(serializers.Serializer):
    """
    Serializes a single waypoint step in the optimized mobile picking route.
    """
    step_number = serializers.IntegerField()
    rack_id = serializers.CharField(source='rack.rack_id')
    zone = serializers.CharField(source='rack.zone')
    x_coord = serializers.FloatField(source='rack.x_coord')
    y_coord = serializers.FloatField(source='rack.y_coord')
    batch_number = serializers.CharField(source='batch.batch_number')
    sku = serializers.CharField(source='batch.sku_id')
    product_name = serializers.CharField(source='batch.sku.name')
    quantity_to_pick = serializers.IntegerField()


class PickPathOutputSerializer(serializers.Serializer):
    """
    Serializes the complete optimized pick tour with baseline comparisons
    for consumption by warehouse mobile clients.
    """
    order_id = serializers.IntegerField(source='order.id')
    order_number = serializers.CharField(source='order.order_number')
    order_status = serializers.CharField(source='order.status')
    total_distance = serializers.FloatField()
    baseline_distance = serializers.FloatField()
    distance_savings_meters = serializers.SerializerMethodField()
    distance_savings_percent = serializers.SerializerMethodField()
    total_steps = serializers.SerializerMethodField()
    steps = PickPathStepSerializer(many=True, read_only=True)

    def get_distance_savings_meters(self, obj):
        diff = obj.baseline_distance - obj.total_distance
        return round(max(0.0, diff), 2)

    def get_distance_savings_percent(self, obj):
        if obj.baseline_distance and obj.baseline_distance > 0:
            pct = ((obj.baseline_distance - obj.total_distance) / obj.baseline_distance) * 100.0
            return round(max(0.0, pct), 1)
        return 0.0

    def get_total_steps(self, obj):
        return obj.steps.count()


class ReturnCategorizeSerializer(serializers.Serializer):
    """
    Validates categorization of returns into Reusable (reslotted) or Damaged (written-off).
    """
    category = serializers.ChoiceField(choices=['Reusable', 'Damaged'], required=True)


