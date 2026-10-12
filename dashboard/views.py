from django.contrib import messages
from django.shortcuts import redirect, render
from django.views import View

from orders.models import Order
from orders.services.allocation_service import (
    AllocationLockError,
    InsufficientStockError,
    OrderStateError,
    approve_and_allocate_order,
)


class PendingOrdersDashboardView(View):
    """
    Manager Dashboard view to list pending orders and execute
    FEFO allocation and picking route optimization upon approval.
    """
    template_name = 'dashboard/pending_orders.html'

    def get(self, request, *args, **kwargs):
        pending_orders = (
            Order.objects.filter(status='pending_approval')
            .prefetch_related('items__product')
            .order_by('-order_date')
        )
        approved_orders = (
            Order.objects.filter(status='approved')
            .select_related('pick_path')
            .prefetch_related('pick_path__steps__rack')
            .order_by('-updated_at')[:10]
        )
        return render(
            request,
            self.template_name,
            {
                'pending_orders': pending_orders,
                'approved_orders': approved_orders,
            }
        )

    def post(self, request, *args, **kwargs):
        order_id = request.POST.get('order_id')
        if not order_id:
            messages.error(request, "No order ID specified for approval.")
            return redirect('dashboard:pending-orders')

        approver = request.user if request.user.is_authenticated else None

        try:
            order = approve_and_allocate_order(order_id, approved_by=approver)
            messages.success(
                request,
                f"Order #{order.order_number} successfully approved! FEFO batches allocated and optimized pick path generated."
            )
        except AllocationLockError as lock_err:
            messages.error(
                request,
                f"Lock Conflict: {lock_err} A concurrent warehouse process is updating inventory. Please retry."
            )
        except InsufficientStockError as stock_err:
            messages.error(
                request,
                f"Allocation Failed: {stock_err}"
            )
        except OrderStateError as state_err:
            messages.warning(
                request,
                f"State Warning: {state_err}"
            )
        except Exception as ex:
            messages.error(
                request,
                f"Unexpected error during order approval: {ex}"
            )

        return redirect('dashboard:pending-orders')


class ManagerOverviewDashboardView(View):
    """
    Manager Overview Dashboard (/dashboard/overview/):
    Gathers and displays:
      1. Order counts by status
      2. Stock-on-hand grouped by ABC class
      3. List of Stores with their current running ledger balance
    """
    template_name = 'dashboard/overview.html'

    def get(self, request, *args, **kwargs):
        from django.contrib.auth import get_user_model
        from django.db.models import Count, Sum, Value
        from django.db.models.functions import Coalesce
        from inventory.models import StockBatch
        from orders.models import Invoice, LedgerEntry

        User = get_user_model()

        # 1. Order counts by status
        raw_counts = dict(
            Order.objects.values('status')
            .annotate(cnt=Count('id'))
            .values_list('status', 'cnt')
        )
        status_definitions = [
            ('pending_approval', 'Pending Approval'),
            ('approved', 'Approved'),
            ('packing', 'Packing'),
            ('packed', 'Packed'),
            ('billed', 'Billed'),
            ('dispatched', 'Dispatched'),
            ('delivered', 'Delivered'),
            ('completed', 'Completed'),
        ]
        order_status_summary = [
            {
                'status_key': key,
                'status_label': label,
                'count': raw_counts.get(key, 0)
            }
            for key, label in status_definitions
        ]
        total_orders = Order.objects.count()

        # 2. Stock-on-hand grouped by ABC class
        raw_abc = dict(
            StockBatch.objects.values('sku__abc_class')
            .annotate(total_qty=Coalesce(Sum('quantity'), Value(0)))
            .values_list('sku__abc_class', 'total_qty')
        )
        total_stock_units = sum(raw_abc.values())
        stock_abc_summary = [
            {
                'abc_class': 'A',
                'label': 'Class A (Fast Mover / High Turnover)',
                'quantity': raw_abc.get('A', 0),
                'percent': round((raw_abc.get('A', 0) / total_stock_units * 100), 1) if total_stock_units else 0,
            },
            {
                'abc_class': 'B',
                'label': 'Class B (Medium Velocity)',
                'quantity': raw_abc.get('B', 0),
                'percent': round((raw_abc.get('B', 0) / total_stock_units * 100), 1) if total_stock_units else 0,
            },
            {
                'abc_class': 'C',
                'label': 'Class C (Slow Moving / Tail)',
                'quantity': raw_abc.get('C', 0),
                'percent': round((raw_abc.get('C', 0) / total_stock_units * 100), 1) if total_stock_units else 0,
            },
        ]

        # 3. List of Stores with current running ledger balance
        stores_with_entries = (
            User.objects.filter(ledger_entries__isnull=False)
            .distinct()
            .order_by('username')
        )
        store_ledgers = []
        total_outstanding_receivables = 0.0

        for st in stores_with_entries:
            latest = st.ledger_entries.order_by('-id').first()
            if latest:
                bal = float(latest.balance_after)
                total_outstanding_receivables += bal
                store_ledgers.append({
                    'store_id': st.id,
                    'store_name': st.get_full_name() or st.username,
                    'username': st.username,
                    'current_balance': latest.balance_after,
                    'last_type': latest.type,
                    'last_amount': latest.amount,
                    'last_updated': latest.created_at,
                })

        # Invoices metrics
        from decimal import Decimal
        from django.db.models import DecimalField
        total_billed_amount = (
            Invoice.objects.aggregate(
                total=Coalesce(
                    Sum('invoice_total'),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=14, decimal_places=2)
                )
            )['total']
        )


        return render(
            request,
            self.template_name,
            {
                'order_status_summary': order_status_summary,
                'total_orders': total_orders,
                'stock_abc_summary': stock_abc_summary,
                'total_stock_units': total_stock_units,
                'store_ledgers': store_ledgers,
                'total_outstanding_receivables': total_outstanding_receivables,
                'total_billed_amount': total_billed_amount,
            }
        )

