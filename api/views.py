from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.contrib.auth import get_user_model
from django.utils import timezone

from api.serializers import (
    PickPathOutputSerializer,
    ReturnCategorizeSerializer,
    StockBatchOutputSerializer,
    StockBatchReceiveSerializer,
)
from inventory.models import Product, Rack, Return, StockBatch, StockWriteoff
from inventory.services.slotting_algo import (
    NoAvailableRackError,
    SlottingAlgorithmError,
    assign_rack,
)
from orders.models import Order, OrderItem




class StockReceiveAPIView(APIView):
    """
    API endpoint for Put-away phase stock receipt:
    POST /api/v1/inventory/receive/

    Accepts incoming stock batch data, dynamically determines optimal rack
    assignment via the slotting algorithm (priority tiers & capacity checks),
    and creates the StockBatch record with concurrency protection.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = StockBatchReceiveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data
        sku_code = validated_data['sku']
        quantity = validated_data['quantity']
        batch_number = validated_data['batch_number']
        expiry_date = validated_data.get('expiry_date')
        source = validated_data.get('source', 'fresh_receipt')

        try:
            with transaction.atomic():
                product = Product.objects.select_for_update().get(sku=sku_code)

                # Execute rack assignment via slotting algorithm
                assigned_rack_id = assign_rack(sku=product, incoming_quantity=quantity)
                assigned_rack = Rack.objects.get(rack_id=assigned_rack_id)

                # Create the StockBatch record
                stock_batch = StockBatch.objects.create(
                    sku=product,
                    batch_number=batch_number,
                    quantity=quantity,
                    expiry_date=expiry_date,
                    rack=assigned_rack,
                    source=source,
                    abc_class_at_slotting=product.abc_class or 'C',
                    xyz_class_at_slotting=product.xyz_class or 'Z',
                )

            output_serializer = StockBatchOutputSerializer(stock_batch)
            return Response(
                {
                    "message": "Stock batch received and slotted successfully.",
                    "stock_batch": output_serializer.data,
                    "slotting_metadata": {
                        "assigned_rack": assigned_rack.rack_id,
                        "zone": assigned_rack.zone,
                        "rack_capacity": assigned_rack.capacity,
                        "rack_current_occupancy": assigned_rack.current_occupancy,
                        "abc_class": stock_batch.abc_class_at_slotting,
                        "xyz_class": stock_batch.xyz_class_at_slotting,
                    }
                },
                status=status.HTTP_201_CREATED
            )

        except NoAvailableRackError as err:
            return Response(
                {
                    "error": "Rack capacity constraint exceeded.",
                    "detail": str(err),
                },
                status=status.HTTP_409_CONFLICT
            )
        except SlottingAlgorithmError as err:
            return Response(
                {
                    "error": "Slotting algorithm failure.",
                    "detail": str(err),
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as err:
            return Response(
                {
                    "error": "Internal error during stock receipt processing.",
                    "detail": str(err),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OrderPickPathAPIView(APIView):
    """
    Mobile endpoint for warehouse pickers:
    GET /api/v1/orders/<order_id>/pick-path/

    Returns the optimized sequence of PickPathStep records (Nearest-Neighbour + 2-opt)
    along with coordinates and baseline comparison metrics for Flutter client display.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id, *args, **kwargs):
        # Allow lookup by numerical ID or string order_number
        order = None
        if str(order_id).isdigit():
            order = Order.objects.filter(pk=int(order_id)).first()

        if not order:
            order = Order.objects.filter(order_number=str(order_id)).first()

        if not order:
            return Response(
                {"error": f"Order '{order_id}' was not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if order.status == 'pending_approval':
            return Response(
                {
                    "error": "Order pending approval.",
                    "detail": f"Order #{order.order_number} has not yet been approved or allocated."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            pick_path = order.pick_path
        except Order.pick_path.RelatedObjectDoesNotExist:
            # If approved but pick_path was somehow not created, generate it
            from orders.services.picking_algo import generate_pick_path
            try:
                pick_path = generate_pick_path(order)
            except Exception as e:
                return Response(
                    {
                        "error": "Unable to generate pick path.",
                        "detail": str(e)
                    },
                    status=status.HTTP_404_NOT_FOUND
                )

        serializer = PickPathOutputSerializer(pick_path)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ReturnCategorizeAPIView(APIView):
    """
    POST /api/v1/returns/<return_id>/categorize/
    Payload: {"category": "Reusable" | "Damaged"}

    If "Reusable":
      Routes the item through assign_rack() slotting logic and creates a new StockBatch(source='return').
    If "Damaged":
      Creates a StockWriteoff record instead.
    Marks Return status as 'processed'.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, return_id, *args, **kwargs):
        serializer = ReturnCategorizeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        category = serializer.validated_data['category']

        try:
            with transaction.atomic():
                return_obj = (
                    Return.objects.select_for_update()
                    .select_related('sku')
                    .get(pk=return_id)
                )

                if return_obj.status == 'processed':
                    return Response(
                        {
                            "error": "Return already processed.",
                            "detail": f"Return #{return_obj.id} is already in 'processed' state."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                product = return_obj.sku
                result_details = {}

                if category == 'Reusable':
                    # Route through Phase 1 slotting algorithm
                    assigned_rack_id = assign_rack(
                        sku=product,
                        incoming_quantity=return_obj.quantity
                    )
                    assigned_rack = Rack.objects.get(rack_id=assigned_rack_id)

                    batch_number = f"RET-{return_obj.id}-{int(timezone.now().timestamp())}"
                    stock_batch = StockBatch.objects.create(
                        sku=product,
                        batch_number=batch_number,
                        quantity=return_obj.quantity,
                        rack=assigned_rack,
                        source='return',
                        abc_class_at_slotting=product.abc_class or 'C',
                        xyz_class_at_slotting=product.xyz_class or 'Z',
                    )
                    result_details = {
                        "action": "re_slotted",
                        "batch_number": stock_batch.batch_number,
                        "assigned_rack": assigned_rack.rack_id,
                        "zone": assigned_rack.zone,
                        "quantity_restocked": stock_batch.quantity,
                    }
                elif category == 'Damaged':
                    # Create StockWriteoff
                    user = request.user if request.user.is_authenticated else None
                    if not user:
                        User = get_user_model()
                        user, _ = User.objects.get_or_create(
                            username='returns_clerk',
                            defaults={'is_active': True}
                        )

                    writeoff = StockWriteoff.objects.create(
                        product=product,
                        quantity=return_obj.quantity,
                        reason=f"Return #{return_obj.id} damaged: {return_obj.reason or 'Inspection rejected'}",
                        written_off_by=user,
                    )
                    result_details = {
                        "action": "written_off",
                        "writeoff_id": writeoff.id,
                        "quantity_written_off": writeoff.quantity,
                    }

                # Mark return processed
                return_obj.category = category
                return_obj.status = 'processed'
                return_obj.save(update_fields=['category', 'status', 'updated_at'])

            return Response(
                {
                    "message": f"Return #{return_obj.id} successfully processed as {category}.",
                    "return_id": return_obj.id,
                    "category": return_obj.category,
                    "status": return_obj.status,
                    "details": result_details,
                },
                status=status.HTTP_200_OK
            )

        except Return.DoesNotExist:
            return Response(
                {"error": f"Return with ID '{return_id}' was not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except NoAvailableRackError as err:
            return Response(
                {"error": "No rack capacity available for reusable return.", "detail": str(err)},
                status=status.HTTP_409_CONFLICT
            )
        except Exception as ex:
            return Response(
                {"error": "Failed to process return.", "detail": str(ex)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class InventoryScanAPIView(APIView):
    """
    Mobile barcode / QR scan verification endpoint:
    POST /api/v1/inventory/scan/
    Payload: {"sku": "string", "rack_id": "string"}

    Validates whether the scanned SKU exists slotted on the specified rack
    within an active StockBatch. Returns 200 OK {"status": "verified"} or 404 Not Found.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        sku = request.data.get('sku')
        rack_id = request.data.get('rack_id')

        if not sku or not rack_id:
            return Response(
                {"error": "Both 'sku' and 'rack_id' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        sku_str = str(sku).strip()
        rack_str = str(rack_id).strip()

        exists = StockBatch.objects.filter(
            sku_id=sku_str,
            rack_id=rack_str
        ).exists()

        if not exists:
            exists = StockBatch.objects.filter(
                sku__sku__iexact=sku_str,
                rack__rack_id__iexact=rack_str
            ).exists()

        if exists:
            return Response({"status": "verified"}, status=status.HTTP_200_OK)


        return Response(
            {
                "error": f"SKU '{sku}' was not found on rack '{rack_id}'.",
                "sku": sku,
                "rack_id": rack_id,
            },
            status=status.HTTP_404_NOT_FOUND
        )


class ProductListAPIView(APIView):
    """
    GET /api/v1/products/
    Returns product catalogue with aggregated available stock across all racks and batches.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        products = Product.objects.all().prefetch_related('stock_batches')
        data = []
        for p in products:
            batches = p.stock_batches.all()
            total_stock = sum(b.quantity for b in batches)
            batch_data = [
                {
                    "batch_number": b.batch_number,
                    "quantity": b.quantity,
                    "expiry_date": str(b.expiry_date) if b.expiry_date else None,
                    "rack_id": b.rack_id,
                }
                for b in batches
            ]
            data.append({
                "sku": p.sku,
                "name": p.name,
                "description": p.description,
                "abc_class": p.abc_class,
                "xyz_class": p.xyz_class,
                "available_stock": total_stock,
                "batches": batch_data,
            })
        return Response(data, status=status.HTTP_200_OK)


class OrderListCreateAPIView(APIView):
    """
    GET /api/v1/orders/
    Lists recent orders with their status and pick path readiness.

    POST /api/v1/orders/
    Payload: {"items": [{"sku": "SKU-...", "quantity": int}]}
    Creates a new Order in 'pending_approval' status.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        orders = Order.objects.all().order_by('-order_date')[:50]
        data = []
        for o in orders:
            has_pick = hasattr(o, 'pick_path')
            data.append({
                "id": o.id,
                "order_number": o.order_number,
                "status": o.status,
                "order_date": o.order_date.isoformat(),
                "item_count": o.items.count(),
                "has_pick_path": has_pick,
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        items_data = request.data.get('items', [])
        if not items_data or not isinstance(items_data, list):
            return Response(
                {"error": "A non-empty 'items' list is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            import uuid
            order_number = f"ORD-{int(timezone.now().timestamp())}-{uuid.uuid4().hex[:4].upper()}"
            store_user = request.user if request.user.is_authenticated else None

            order = Order.objects.create(
                order_number=order_number,
                status='pending_approval',
                store=store_user,
            )

            created_items = []
            for item in items_data:
                sku = item.get('sku')
                qty = item.get('quantity', 1)
                try:
                    product = Product.objects.get(sku=sku)
                except Product.DoesNotExist:
                    return Response(
                        {"error": f"Product with SKU '{sku}' does not exist."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                order_item = OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=int(qty),
                )
                created_items.append({
                    "sku": product.sku,
                    "product_name": product.name,
                    "quantity": order_item.quantity,
                })

        return Response(
            {
                "message": "Order created successfully and queued for approval.",
                "order_id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "items": created_items,
            },
            status=status.HTTP_201_CREATED
        )
