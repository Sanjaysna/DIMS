class ProductBatch {
  final String batchNumber;
  final int quantity;
  final String? expiryDate;
  final String? rackId;

  ProductBatch({
    required this.batchNumber,
    required this.quantity,
    this.expiryDate,
    this.rackId,
  });

  factory ProductBatch.fromJson(Map<String, dynamic> json) {
    return ProductBatch(
      batchNumber: json['batch_number']?.toString() ?? '',
      quantity: json['quantity'] is int
          ? json['quantity'] as int
          : int.tryParse(json['quantity']?.toString() ?? '0') ?? 0,
      expiryDate: json['expiry_date']?.toString(),
      rackId: json['rack_id']?.toString(),
    );
  }
}

class ProductItem {
  final String sku;
  final String name;
  final String description;
  final String? abcClass;
  final String? xyzClass;
  final int availableStock;
  final List<ProductBatch> batches;

  ProductItem({
    required this.sku,
    required this.name,
    required this.description,
    this.abcClass,
    this.xyzClass,
    required this.availableStock,
    required this.batches,
  });

  factory ProductItem.fromJson(Map<String, dynamic> json) {
    final rawBatches = json['batches'] as List<dynamic>? ?? [];
    return ProductItem(
      sku: json['sku']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      description: json['description']?.toString() ?? '',
      abcClass: json['abc_class']?.toString(),
      xyzClass: json['xyz_class']?.toString(),
      availableStock: json['available_stock'] is int
          ? json['available_stock'] as int
          : int.tryParse(json['available_stock']?.toString() ?? '0') ?? 0,
      batches: rawBatches
          .map((b) => ProductBatch.fromJson(b as Map<String, dynamic>))
          .toList(),
    );
  }
}
