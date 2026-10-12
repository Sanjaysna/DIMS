from django.db import transaction
from rest_framework import status
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
from orders.models import Order




class StockReceiveAPIView(APIView):
    """
    API endpoint for Put-away phase stock receipt:
    POST /api/v1/inventory/receive/

    Accepts incoming stock batch data, dynamically determines optimal rack
    assignment via the slotting algorithm (priority tiers & capacity checks),
    and creates the StockBatch record with concurrency protection.
    """

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


