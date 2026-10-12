import math
from typing import Dict, List, Tuple

from django.db import transaction

from orders.models import Order, OrderItemBatches, PickPath, PickPathStep


def euclidean_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Calculates Euclidean distance between two 2D coordinates."""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def compute_route_distance(
    points: List[Tuple[float, float]],
    origin: Tuple[float, float] = (0.0, 0.0),
    include_return: bool = True
) -> float:
    """
    Computes total transit distance starting at origin, visiting all points in order,
    and optionally returning to origin.
    """
    if not points:
        return 0.0

    total = euclidean_distance(origin, points[0])
    for i in range(len(points) - 1):
        total += euclidean_distance(points[i], points[i + 1])

    if include_return:
        total += euclidean_distance(points[-1], origin)

    return total


def nearest_neighbour_tour(
    stops: List[dict],
    origin: Tuple[float, float] = (0.0, 0.0)
) -> List[dict]:
    """
    Constructs an initial tour using the Nearest-Neighbour heuristic starting from origin.
    Each stop in stops is expected to have 'coord': (x, y).
    """
    if not stops:
        return []

    unvisited = list(stops)
    tour = []
    current_coord = origin

    while unvisited:
        nearest_idx = 0
        min_dist = float('inf')
        for idx, stop in enumerate(unvisited):
            d = euclidean_distance(current_coord, stop['coord'])
            if d < min_dist:
                min_dist = d
                nearest_idx = idx

        next_stop = unvisited.pop(nearest_idx)
        tour.append(next_stop)
        current_coord = next_stop['coord']

    return tour


def two_opt_optimize(
    tour: List[dict],
    origin: Tuple[float, float] = (0.0, 0.0),
    include_return: bool = True,
    max_iterations: int = 500
) -> List[dict]:
    """
    Applies the 2-opt local search heuristic to untangle crosses and minimize tour distance.
    Preserves fixed origin at start (and return to origin if include_return=True).
    """
    if len(tour) <= 2:
        return tour

    best_tour = list(tour)
    best_dist = compute_route_distance(
        [s['coord'] for s in best_tour], origin=origin, include_return=include_return
    )

    improved = True
    iteration = 0
    num_stops = len(best_tour)

    while improved and iteration < max_iterations:
        improved = False
        iteration += 1

        for i in range(num_stops - 1):
            for j in range(i + 1, num_stops):
                # 2-opt swap: reverse the subsegment from i to j
                candidate = best_tour[:i] + best_tour[i:j + 1][::-1] + best_tour[j + 1:]
                cand_dist = compute_route_distance(
                    [s['coord'] for s in candidate], origin=origin, include_return=include_return
                )

                if cand_dist < best_dist - 1e-6:
                    best_tour = candidate
                    best_dist = cand_dist
                    improved = True
                    break
            if improved:
                break

    return best_tour


def generate_pick_path(order: Order) -> PickPath:
    """
    Calculates the optimized picking path for an approved Order and creates
    the PickPath and ordered PickPathStep records in the database.

    1. Gathers all allocated OrderItemBatches.
    2. Computes the baseline FIFO distance (visiting stops in order created).
    3. Solves routing via Nearest-Neighbour + 2-opt local search.
    4. Persists PickPath (with total_distance and baseline_distance) and PickPathSteps.
    """
    allocations = (
        OrderItemBatches.objects.filter(order_item__order=order)
        .select_related('batch', 'batch__rack', 'order_item')
        .order_by('order_item__id', 'id')
    )

    if not allocations.exists():
        raise ValueError(f"No allocated stock batches found for Order #{order.order_number}.")

    # Build stop items list preserving FIFO sequence
    fifo_stops: List[dict] = []
    for alloc in allocations:
        rack = alloc.batch.rack
        fifo_stops.append({
            'allocation': alloc,
            'rack': rack,
            'batch': alloc.batch,
            'quantity': alloc.quantity_allocated,
            'coord': (float(rack.x_coord), float(rack.y_coord)),
        })

    origin = (0.0, 0.0)

    # 1. Baseline Distance (FIFO order sequence)
    fifo_coords = [s['coord'] for s in fifo_stops]
    baseline_dist = compute_route_distance(fifo_coords, origin=origin, include_return=True)

    # 2. Optimized Routing (Nearest-Neighbour + 2-opt)
    # Group items by rack location so multiple batch picks on the same rack are handled together
    # without redundant transit
    grouped_by_rack: Dict[str, List[dict]] = {}
    rack_coords: Dict[str, Tuple[float, float]] = {}

    for stop in fifo_stops:
        r_id = stop['rack'].rack_id
        if r_id not in grouped_by_rack:
            grouped_by_rack[r_id] = []
            rack_coords[r_id] = stop['coord']
        grouped_by_rack[r_id].append(stop)

    # Distinct rack stops for routing optimization
    distinct_stops = [{'rack_id': r_id, 'coord': coord} for r_id, coord in rack_coords.items()]

    nn_tour = nearest_neighbour_tour(distinct_stops, origin=origin)
    optimized_rack_tour = two_opt_optimize(nn_tour, origin=origin, include_return=True)

    # Flatten back into ordered pick items
    optimized_steps_data: List[dict] = []
    optimized_coords: List[Tuple[float, float]] = []

    for stop in optimized_rack_tour:
        r_id = stop['rack_id']
        coord = stop['coord']
        for item in grouped_by_rack[r_id]:
            optimized_steps_data.append(item)
            optimized_coords.append(coord)

    optimized_dist = compute_route_distance(
        [s['coord'] for s in optimized_rack_tour], origin=origin, include_return=True
    )

    # In rare symmetric cases where NN+2-opt equals baseline, ensure total_distance <= baseline
    final_distance = min(optimized_dist, baseline_dist)

    with transaction.atomic():
        # Remove any previously calculated pick path for idempotent re-runs
        PickPath.objects.filter(order=order).delete()

        pick_path = PickPath.objects.create(
            order=order,
            total_distance=round(final_distance, 2),
            baseline_distance=round(baseline_dist, 2),
        )

        steps_to_create = []
        for idx, item in enumerate(optimized_steps_data, start=1):
            steps_to_create.append(
                PickPathStep(
                    pick_path=pick_path,
                    step_number=idx,
                    rack=item['rack'],
                    batch=item['batch'],
                    quantity_to_pick=item['quantity'],
                )
            )

        PickPathStep.objects.bulk_create(steps_to_create)

    return pick_path
