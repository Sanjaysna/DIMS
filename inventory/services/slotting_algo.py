import datetime
import math
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Union

from django.db import DatabaseError, OperationalError, transaction
from django.db.models import Case, DecimalField, F, IntegerField, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from inventory.models import Product, Rack, StockBatch
from orders.models import OrderItem


class SlottingAlgorithmError(Exception):
    """Base exception for slotting algorithm failures."""
    pass


class NoAvailableRackError(SlottingAlgorithmError):
    """Raised when no rack with adequate remaining capacity is found."""
    pass


# Warehouse zone tier definitions
TIER_1_ZONES = ['AX', 'AY']
TIER_2_ZONES = ['BX', 'BY']
TIER_3_ZONES = ['AZ', 'BZ', 'CX', 'CY']
TIER_4_ZONES = ['CZ']


def calculate_abc_xyz(
    target_sku: Optional[str] = None,
    months: int = 6,
    update_products: bool = True
) -> Dict[str, Dict[str, str]]:
    """
    Calculates ABC and XYZ inventory classifications.
    CRITICAL: Strictly bounds queries to a rolling 6-month window of order history
    to prevent full-table scan crashes on high-volume transactional data.

    ABC Logic (Pareto Consumption Value):
      - A: Top 70% of total revenue/turnover
      - B: Next 20% (70% - 90%)
      - C: Remaining 10% (90% - 100%) or unmoving items

    XYZ Logic (Demand Volatility / Coefficient of Variation CV = std_dev / mean):
      - X: CV <= 0.5 (steady, high predictability)
      - Y: 0.5 < CV <= 1.0 (moderate variability)
      - Z: CV > 1.0 (sporadic / erratic / low predictability)
    """
    cutoff_date = timezone.now() - datetime.timedelta(days=30 * months)

    # 1. Bounded OrderItem query strictly limited to rolling window
    items_qs = OrderItem.objects.filter(
        order__order_date__gte=cutoff_date
    ).exclude(order__status='cancelled')


    if target_sku:
        products_qs = Product.objects.filter(sku=target_sku)
    else:
        products_qs = Product.objects.all()

    # 2. ABC: Calculate total consumption value per SKU in the window
    # value = quantity * unit_price
    sales_by_sku = (
        items_qs.values('product_id')
        .annotate(
            total_value=Coalesce(
                Sum(
                    F('quantity') * F('unit_price'),
                    output_field=DecimalField(max_digits=14, decimal_places=2)
                ),
                Value(Decimal('0.00'))
            ),
            total_units=Coalesce(Sum('quantity'), Value(0))
        )
    )

    sku_value_map: Dict[str, Decimal] = {
        row['product_id']: row['total_value'] for row in sales_by_sku
    }

    # Aggregate global total value for the rolling window
    all_window_skus = list(products_qs.values_list('sku', flat=True))
    total_revenue = sum(sku_value_map.get(sku, Decimal('0.00')) for sku in all_window_skus)

    # Sort SKUs descending by consumption value
    sorted_skus = sorted(
        all_window_skus,
        key=lambda s: sku_value_map.get(s, Decimal('0.00')),
        reverse=True
    )

    abc_results: Dict[str, str] = {}
    running_sum = Decimal('0.00')

    for sku in sorted_skus:
        val = sku_value_map.get(sku, Decimal('0.00'))
        if total_revenue > Decimal('0.00') and val > Decimal('0.00'):
            prior_pct = (running_sum / total_revenue) * Decimal('100.00')
            running_sum += val
            if prior_pct < Decimal('70.00'):
                abc_results[sku] = 'A'
            elif prior_pct < Decimal('90.00'):
                abc_results[sku] = 'B'
            else:
                abc_results[sku] = 'C'
        else:
            abc_results[sku] = 'C'


    # 3. XYZ: Calculate monthly demand volatility over the 6 monthly buckets
    bucket_length_days = 30
    bucket_start_dates = [
        cutoff_date + datetime.timedelta(days=i * bucket_length_days)
        for i in range(months)
    ]

    # Map sku -> list of demand per monthly bucket
    monthly_demand: Dict[str, List[int]] = {sku: [0] * months for sku in all_window_skus}

    for i, start in enumerate(bucket_start_dates):
        end = start + datetime.timedelta(days=bucket_length_days)
        bucket_qs = items_qs.filter(
            order__order_date__gte=start,
            order__order_date__lt=end
        ).values('product_id').annotate(bucket_qty=Coalesce(Sum('quantity'), Value(0)))

        for row in bucket_qs:
            prod_id = row['product_id']
            if prod_id in monthly_demand:
                monthly_demand[prod_id][i] = row['bucket_qty']

    xyz_results: Dict[str, str] = {}
    for sku in all_window_skus:
        demands = monthly_demand.get(sku, [0] * months)
        n = len(demands)
        mean = sum(demands) / n if n > 0 else 0.0

        if mean == 0:
            xyz_results[sku] = 'Z'
            continue

        variance = sum((x - mean) ** 2 for x in demands) / n
        std_dev = math.sqrt(variance)
        cv = std_dev / mean

        if cv <= 0.5:
            xyz_results[sku] = 'X'
        elif cv <= 1.0:
            xyz_results[sku] = 'Y'
        else:
            xyz_results[sku] = 'Z'

    # Consolidate classification results
    classifications: Dict[str, Dict[str, str]] = {}
    for sku in all_window_skus:
        c_abc = abc_results.get(sku, 'C')
        c_xyz = xyz_results.get(sku, 'Z')
        classifications[sku] = {'abc_class': c_abc, 'xyz_class': c_xyz}

    # Optionally persist cached classification to Product model
    if update_products and classifications:
        for sku, classes in classifications.items():
            Product.objects.filter(sku=sku).update(
                abc_class=classes['abc_class'],
                xyz_class=classes['xyz_class']
            )

    return classifications


def get_zone_tier_priorities(abc_class: Optional[str], xyz_class: Optional[str]) -> List[List[str]]:
    """
    Resolves the ordered zone tier search order based on ABC/XYZ category:
      - Tier 1 (AX, AY): Fastest moving, high/moderate predictability -> Nearest to dispatch.
      - Tier 2 (AZ, BX, BY): Moderate velocity.
      - Tier 3 (BZ, CX, CY): Slower movement.
      - Tier 4 (CZ): Slowest moving, sporadic demand -> Farthest from dispatch.
    """
    combo = f"{abc_class or 'C'}{xyz_class or 'Z'}".upper()

    if combo in ['AX', 'AY']:
        return [TIER_1_ZONES, TIER_2_ZONES, TIER_3_ZONES, TIER_4_ZONES]
    elif combo in ['AZ', 'BX', 'BY']:
        return [TIER_2_ZONES, TIER_1_ZONES, TIER_3_ZONES, TIER_4_ZONES]
    elif combo in ['BZ', 'CX', 'CY']:
        return [TIER_3_ZONES, TIER_4_ZONES, TIER_2_ZONES, TIER_1_ZONES]
    else:  # Default/CZ
        return [TIER_4_ZONES, TIER_3_ZONES, TIER_2_ZONES, TIER_1_ZONES]


def assign_rack(sku: Union[str, Product], incoming_quantity: int = 1) -> str:
    """
    Selects and reserves the optimal rack for an incoming SKU batch.
    - Resolves SKU ABC/XYZ classification.
    - Evaluates priority tiers (AX/AY Tier 1 down to CZ Tier 4).
    - Checks current occupancy against Rack.capacity.
    - Handles PostgreSQL concurrency gracefully via row locking (select_for_update).
    - Returns assigned rack_id.
    """
    if incoming_quantity <= 0:
        raise ValueError("Incoming quantity must be greater than zero.")

    if isinstance(sku, Product):
        product = sku
        sku_code = product.sku
    else:
        sku_code = str(sku)
        try:
            product = Product.objects.get(sku=sku_code)
        except Product.DoesNotExist:
            raise SlottingAlgorithmError(f"Product with SKU '{sku_code}' does not exist.")

    # Check cached ABC/XYZ; calculate if missing
    abc_class = product.abc_class
    xyz_class = product.xyz_class

    if not abc_class or not xyz_class:
        calc = calculate_abc_xyz(target_sku=sku_code, update_products=True)
        if sku_code in calc:
            abc_class = calc[sku_code]['abc_class']
            xyz_class = calc[sku_code]['xyz_class']
        else:
            abc_class = abc_class or 'C'
            xyz_class = xyz_class or 'Z'

    tier_order = get_zone_tier_priorities(abc_class, xyz_class)

    # Flatten prioritized zones
    ordered_zones: List[str] = []
    for tier in tier_order:
        for z in tier:
            if z not in ordered_zones:
                ordered_zones.append(z)

    # Perform atomic selection with concurrency protection
    try:
        with transaction.atomic():
            # Query candidate racks matching capacity criteria
            # Using select_for_update() to lock racks and avoid race-condition overcommit
            # 1. Check in prioritized zones first
            for target_zones in tier_order:
                candidate_rack = _find_available_rack_in_zones(
                    target_zones, incoming_quantity
                )
                if candidate_rack:
                    return candidate_rack.rack_id

            # 2. Fallback to any remaining rack in the warehouse with capacity
            fallback_rack = _find_available_rack_anywhere(incoming_quantity)
            if fallback_rack:
                return fallback_rack.rack_id

            raise NoAvailableRackError(
                f"No rack with sufficient capacity ({incoming_quantity} units) available for SKU '{sku_code}'."
            )

    except (OperationalError, DatabaseError) as db_err:
        raise SlottingAlgorithmError(f"Database error during rack assignment: {db_err}") from db_err


def _find_available_rack_in_zones(zones: List[str], required_capacity: int) -> Optional[Rack]:
    """Helper to find and lock the best available rack in designated zones."""
    candidate_racks = (
        Rack.objects.filter(zone__in=zones)
        .annotate(
            occupied=Coalesce(
                Sum('stock_batches__quantity'),
                Value(0),
                output_field=IntegerField()
            )
        )
        .filter(capacity__gte=F('occupied') + required_capacity)
        .order_by('x_coord', 'y_coord', 'rack_id')
    )

    for cand in candidate_racks:
        # Acquire row lock on this rack to guarantee capacity isolation
        locked_rack = (
            Rack.objects.select_for_update()
            .filter(rack_id=cand.rack_id)
            .first()
        )
        if not locked_rack:
            continue

        # Re-verify occupancy with the lock held
        current_occ = (
            StockBatch.objects.filter(rack=locked_rack)
            .aggregate(total=Coalesce(Sum('quantity'), Value(0)))['total']
        )
        if current_occ + required_capacity <= locked_rack.capacity:
            return locked_rack

    return None


def _find_available_rack_anywhere(required_capacity: int) -> Optional[Rack]:
    """Helper to find and lock any rack in warehouse with required capacity."""
    candidate_racks = (
        Rack.objects.all()
        .annotate(
            occupied=Coalesce(
                Sum('stock_batches__quantity'),
                Value(0),
                output_field=IntegerField()
            )
        )
        .filter(capacity__gte=F('occupied') + required_capacity)
        .order_by('rack_id')
    )

    for cand in candidate_racks:
        locked_rack = (
            Rack.objects.select_for_update()
            .filter(rack_id=cand.rack_id)
            .first()
        )
        if not locked_rack:
            continue

        current_occ = (
            StockBatch.objects.filter(rack=locked_rack)
            .aggregate(total=Coalesce(Sum('quantity'), Value(0)))['total']
        )
        if current_occ + required_capacity <= locked_rack.capacity:
            return locked_rack

    return None
