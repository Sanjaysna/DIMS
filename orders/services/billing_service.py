from decimal import Decimal
from typing import Union

from django.contrib.auth import get_user_model
from django.db import transaction

from orders.models import Invoice, InvoiceItem, LedgerEntry, Order

User = get_user_model()


class BillingError(Exception):
    """Base exception for billing operations."""
    pass


class BillingStateError(BillingError):
    """Raised when an order is not in the required 'packed' state for billing."""
    pass


def generate_invoice(order_id: Union[int, str, Order]) -> Invoice:
    """
    Generates an Invoice and InvoiceItems for a packed order, updates order status to 'billed',
    and atomically updates the Store's running accounts-receivable ledger balance.

    CRITICAL RULES:
    1. Must only execute if order.status == 'packed'.
    2. Atomic Ledger Update: Exclusively locks the store's account via select_for_update(),
       retrieves the latest ledger balance, computes new_balance = old_balance + invoice_total,
       and inserts a new LedgerEntry (type='charge').
    """
    with transaction.atomic():
        # Retrieve and lock order
        if isinstance(order_id, Order):
            order = Order.objects.select_for_update().get(pk=order_id.pk)
        elif isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit()):
            order = Order.objects.select_for_update().get(pk=int(order_id))
        else:
            order = Order.objects.select_for_update().get(order_number=str(order_id))

        if order.status != 'packed':
            raise BillingStateError(
                f"Order #{order.order_number} cannot be billed. "
                f"Status must be 'packed', but found '{order.status}'."
            )

        if hasattr(order, 'invoice'):
            raise BillingError(f"Invoice already exists for Order #{order.order_number}.")

        order_items = order.items.select_related('product').all()
        if not order_items.exists():
            raise BillingError(f"Order #{order.order_number} has no line items to bill.")

        # Compute invoice line totals and aggregate invoice_total
        invoice_total = Decimal('0.00')
        line_item_data = []

        for item in order_items:
            unit_price = Decimal(str(item.unit_price))
            quantity = item.quantity
            line_total = (unit_price * Decimal(quantity)).quantize(Decimal('0.01'))
            invoice_total += line_total
            line_item_data.append({
                'sku': item.product,
                'unit_price': unit_price,
                'quantity': quantity,
                'line_total': line_total,
            })

        # 1. Create Invoice record
        invoice = Invoice.objects.create(
            order=order,
            invoice_total=invoice_total
        )

        # 2. Create InvoiceItem snapshot records
        invoice_items_to_create = [
            InvoiceItem(
                invoice=invoice,
                sku=ld['sku'],
                unit_price=ld['unit_price'],
                quantity=ld['quantity'],
                line_total=ld['line_total'],
            )
            for ld in line_item_data
        ]
        InvoiceItem.objects.bulk_create(invoice_items_to_create)

        # 3. Update order status to 'billed'
        order.status = 'billed'
        order.save(update_fields=['status', 'updated_at'])

        # 4. Atomic Ledger Update with strict serialized locking per store
        store = order.store or order.approved_by
        if not store:
            store, _ = User.objects.get_or_create(
                username='default_store',
                defaults={'is_active': True}
            )
            order.store = store
            order.save(update_fields=['store'])

        # Exclusively lock store record to serialize concurrent billing operations
        locked_store = User.objects.select_for_update().get(pk=store.pk)

        # Fetch latest ledger entry under locked transaction
        latest_entry = (
            LedgerEntry.objects.filter(store=locked_store)
            .select_for_update()
            .order_by('-id')
            .first()
        )

        old_balance = latest_entry.balance_after if latest_entry else Decimal('0.00')
        new_balance = (old_balance + invoice_total).quantize(Decimal('0.01'))

        # Insert new LedgerEntry
        LedgerEntry.objects.create(
            store=locked_store,
            invoice=invoice,
            amount=invoice_total,
            type='charge',
            balance_after=new_balance,
        )

        return invoice
