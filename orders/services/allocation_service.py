from typing import Optional, Union

from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models import F
from django.utils import timezone

from inventory.models import StockBatch
from orders.models import Order, OrderItem, OrderItemBatches
from orders.services.picking_algo import generate_pick_path


class AllocationError(Exception):
    """Base exception for inventory allocation failures."""
    pass


class AllocationLockError(AllocationError):
    """
    Raised when non-blocking lock acquisition fails (nowait=True)
    due to another concurrent process holding a row lock.
    """
    pass


class InsufficientStockError(AllocationError):
    """Raised when available inventory is insufficient to satisfy the requested quantity."""
    pass


class OrderStateError(AllocationError):
    """Raised when the order is not in a valid state for approval/allocation."""
    pass


def approve_and_allocate_order(
    order_id: Union[int, str, Order],
    approved_by: Optional[settings.AUTH_USER_MODEL] = None
) -> Order:
    """
    Approves an order and allocates stock batches strictly following First-Expiry-First-Out (FEFO).

    CRITICAL CONCURRENCY CONTROL:
    - Acquires row locks on StockBatch using select_for_update(nowait=True) inside transaction.atomic().
    - If any candidate batch is currently held by another transaction, PostgreSQL raises OperationalError.
    - We catch this and immediately raise AllocationLockError so the calling view can prompt the user to retry.

    After successful allocation:
    - Marks order status as 'approved', records approver and timestamp.
    - Automatically invokes generate_pick_path(order) to calculate and store the optimized NN + 2-opt pick tour.
    """
    try:
        with transaction.atomic():
            # Retrieve and lock order
            if isinstance(order_id, Order):
                order = Order.objects.select_for_update().get(pk=order_id.pk)
            elif isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit()):
                order = Order.objects.select_for_update().get(pk=int(order_id))
            else:
                order = Order.objects.select_for_update().get(order_number=str(order_id))

            if order.status != 'pending_approval':
                raise OrderStateError(
                    f"Order #{order.order_number} cannot be approved because it has status '{order.status}'."
                )

            order_items = order.items.select_related('product').all()
            if not order_items.exists():
                raise AllocationError(f"Order #{order.order_number} contains no line items to allocate.")

            # Iterate through each item and allocate via FEFO
            for item in order_items:
                remaining_needed = item.quantity

                # Query available batches ordered by expiry_date ascending (FEFO)
                # Null expiry dates are sorted last
                try:
                    candidate_batches = list(
                        StockBatch.objects.filter(sku=item.product, quantity__gt=0)
                        .order_by(F('expiry_date').asc(nulls_last=True), 'id')
                        .select_for_update(nowait=True)
                    )
                except OperationalError as op_err:
                    raise AllocationLockError(
                        f"Inventory for SKU '{item.product.sku}' is currently locked by another concurrent process. "
                        "Please retry in a moment."
                    ) from op_err

                total_available = sum(b.quantity for b in candidate_batches)
                if total_available < remaining_needed:
                    raise InsufficientStockError(
                        f"Insufficient stock for SKU '{item.product.sku}'. "
                        f"Requested: {remaining_needed}, Available: {total_available}."
                    )

                for batch in candidate_batches:
                    if remaining_needed <= 0:
                        break

                    allocated_qty = min(batch.quantity, remaining_needed)
                    batch.quantity -= allocated_qty
                    batch.save(update_fields=['quantity', 'updated_at'])

                    OrderItemBatches.objects.create(
                        order_item=item,
                        batch=batch,
                        quantity_allocated=allocated_qty
                    )

                    remaining_needed -= allocated_qty

            # Update Order state
            order.status = 'approved'
            order.approved_by = approved_by
            order.approved_at = timezone.now()
            order.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

            # Generate the optimized picking path
            generate_pick_path(order)

            return order

    except Order.DoesNotExist:
        raise AllocationError(f"Order with identifier '{order_id}' was not found.")
