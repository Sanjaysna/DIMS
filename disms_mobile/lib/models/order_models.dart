class OrderSummary {
  final int id;
  final String orderNumber;
  final String status;
  final String orderDate;
  final int itemCount;
  final bool hasPickPath;

  OrderSummary({
    required this.id,
    required this.orderNumber,
    required this.status,
    required this.orderDate,
    required this.itemCount,
    required this.hasPickPath,
  });

  factory OrderSummary.fromJson(Map<String, dynamic> json) {
    return OrderSummary(
      id: json['id'] is int
          ? json['id'] as int
          : int.tryParse(json['id']?.toString() ?? '0') ?? 0,
      orderNumber: json['order_number']?.toString() ?? '',
      status: json['status']?.toString() ?? 'pending_approval',
      orderDate: json['order_date']?.toString() ?? '',
      itemCount: json['item_count'] is int
          ? json['item_count'] as int
          : int.tryParse(json['item_count']?.toString() ?? '0') ?? 0,
      hasPickPath: json['has_pick_path'] == true,
    );
  }
}

class OrderCreateResponse {
  final int orderId;
  final String orderNumber;
  final String status;
  final String message;

  OrderCreateResponse({
    required this.orderId,
    required this.orderNumber,
    required this.status,
    required this.message,
  });

  factory OrderCreateResponse.fromJson(Map<String, dynamic> json) {
    return OrderCreateResponse(
      orderId: json['order_id'] is int
          ? json['order_id'] as int
          : int.tryParse(json['order_id']?.toString() ?? '0') ?? 0,
      orderNumber: json['order_number']?.toString() ?? '',
      status: json['status']?.toString() ?? 'pending_approval',
      message: json['message']?.toString() ?? 'Order created successfully.',
    );
  }
}

class PickPathStep {
  final int stepNumber;
  final String rackId;
  final String zone;
  final double xCoord;
  final double yCoord;
  final String batchNumber;
  final String sku;
  final String productName;
  final int quantityToPick;
  bool isCompleted;

  PickPathStep({
    required this.stepNumber,
    required this.rackId,
    required this.zone,
    required this.xCoord,
    required this.yCoord,
    required this.batchNumber,
    required this.sku,
    required this.productName,
    required this.quantityToPick,
    this.isCompleted = false,
  });

  factory PickPathStep.fromJson(Map<String, dynamic> json) {
    return PickPathStep(
      stepNumber: json['step_number'] is int
          ? json['step_number'] as int
          : int.tryParse(json['step_number']?.toString() ?? '0') ?? 0,
      rackId: json['rack_id']?.toString() ?? '',
      zone: json['zone']?.toString() ?? '',
      xCoord: (json['x_coord'] as num?)?.toDouble() ?? 0.0,
      yCoord: (json['y_coord'] as num?)?.toDouble() ?? 0.0,
      batchNumber: json['batch_number']?.toString() ?? '',
      sku: json['sku']?.toString() ?? '',
      productName: json['product_name']?.toString() ?? '',
      quantityToPick: json['quantity_to_pick'] is int
          ? json['quantity_to_pick'] as int
          : int.tryParse(json['quantity_to_pick']?.toString() ?? '0') ?? 0,
      isCompleted: false,
    );
  }
}

class PickPathResponse {
  final int orderId;
  final String orderNumber;
  final String orderStatus;
  final double totalDistance;
  final double baselineDistance;
  final double distanceSavingsMeters;
  final double distanceSavingsPercent;
  final int totalSteps;
  final List<PickPathStep> steps;

  PickPathResponse({
    required this.orderId,
    required this.orderNumber,
    required this.orderStatus,
    required this.totalDistance,
    required this.baselineDistance,
    required this.distanceSavingsMeters,
    required this.distanceSavingsPercent,
    required this.totalSteps,
    required this.steps,
  });

  factory PickPathResponse.fromJson(Map<String, dynamic> json) {
    final rawSteps = json['steps'] as List<dynamic>? ?? [];
    final stepsList = rawSteps
        .map((s) => PickPathStep.fromJson(s as Map<String, dynamic>))
        .toList();

    return PickPathResponse(
      orderId: json['order_id'] is int
          ? json['order_id'] as int
          : int.tryParse(json['order_id']?.toString() ?? '0') ?? 0,
      orderNumber: json['order_number']?.toString() ?? '',
      orderStatus: json['order_status']?.toString() ?? '',
      totalDistance: (json['total_distance'] as num?)?.toDouble() ?? 0.0,
      baselineDistance: (json['baseline_distance'] as num?)?.toDouble() ?? 0.0,
      distanceSavingsMeters:
          (json['distance_savings_meters'] as num?)?.toDouble() ?? 0.0,
      distanceSavingsPercent:
          (json['distance_savings_percent'] as num?)?.toDouble() ?? 0.0,
      totalSteps: json['total_steps'] is int
          ? json['total_steps'] as int
          : stepsList.length,
      steps: stepsList,
    );
  }
}

class ScanVerificationResult {
  final bool isVerified;
  final String? errorMessage;
  final String? sku;
  final String? rackId;

  ScanVerificationResult({
    required this.isVerified,
    this.errorMessage,
    this.sku,
    this.rackId,
  });
}
