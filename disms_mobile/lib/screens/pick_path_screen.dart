import 'package:flutter/material.dart';
import '../models/order_models.dart';
import '../services/api_service.dart';

class PickPathScreen extends StatefulWidget {
  final dynamic initialOrderId;
  final ApiService? apiService;

  const PickPathScreen({
    super.key,
    this.initialOrderId,
    this.apiService,
  });

  @override
  State<PickPathScreen> createState() => _PickPathScreenState();
}

class _PickPathScreenState extends State<PickPathScreen> {
  late final ApiService _apiService;

  dynamic _currentOrderId;
  PickPathResponse? _pickPath;
  List<OrderSummary> _availableOrders = [];

  bool _isLoading = false;
  String? _errorMessage;
  int _activeStepIndex = 0;

  @override
  void initState() {
    super.initState();
    _apiService = widget.apiService ?? ApiService();
    _currentOrderId = widget.initialOrderId;

    if (_currentOrderId != null) {
      _loadPickPath(_currentOrderId);
    } else {
      _loadOrdersForSelection();
    }
  }

  Future<void> _loadPickPath(dynamic orderId) async {
    setState(() {
      _currentOrderId = orderId;
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final response = await _apiService.fetchPickPath(orderId);
      setState(() {
        _pickPath = response;
        _isLoading = false;
        _activeStepIndex = 0;
      });
    } catch (e) {
      setState(() {
        _errorMessage = e.toString().replaceFirst('Exception: ', '');
        _isLoading = false;
      });
    }
  }

  Future<void> _loadOrdersForSelection() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final orders = await _apiService.fetchOrders();
      setState(() {
        _availableOrders = orders;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _errorMessage = e.toString().replaceFirst('Exception: ', '');
        _isLoading = false;
      });
    }
  }

  int get _completedCount =>
      _pickPath?.steps.where((s) => s.isCompleted).length ?? 0;

  bool get _isOrderComplete =>
      _pickPath != null &&
      _pickPath!.steps.isNotEmpty &&
      _completedCount == _pickPath!.steps.length;

  void _openBarcodeVerification(PickPathStep step) {
    final rackController = TextEditingController();
    final skuController = TextEditingController();
    String? localError;
    bool isVerifying = false;

    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setModalState) {
            return Padding(
              padding: EdgeInsets.only(
                bottom: MediaQuery.of(ctx).viewInsets.bottom + 16,
                top: 20,
                left: 20,
                right: 20,
              ),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: const Color(0xFF2563EB).withValues(alpha: 0.1),
                                borderRadius: BorderRadius.circular(10),
                              ),
                              child: const Icon(
                                Icons.qr_code_scanner_rounded,
                                color: Color(0xFF2563EB),
                                size: 22,
                              ),
                            ),
                            const SizedBox(width: 10),
                            Text(
                              'Verify Stop #${step.stepNumber}',
                              style: const TextStyle(
                                fontSize: 17,
                                fontWeight: FontWeight.bold,
                                color: Color(0xFF0F172A),
                              ),
                            ),
                          ],
                        ),
                        IconButton(
                          icon: const Icon(Icons.close),
                          onPressed: () => Navigator.pop(ctx),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),

                    // Expected Stop Info Card
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: const Color(0xFFF1F5F9),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: Colors.grey.shade300),
                      ),
                      child: Column(
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              const Text('Target Rack:', style: TextStyle(fontSize: 12)),
                              Text(
                                step.rackId,
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13,
                                  fontFamily: 'monospace',
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 4),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              const Text('Target SKU:', style: TextStyle(fontSize: 12)),
                              Text(
                                step.sku,
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13,
                                  fontFamily: 'monospace',
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 4),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              const Text('Pick Quantity:', style: TextStyle(fontSize: 12)),
                              Text(
                                '${step.quantityToPick} units',
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13,
                                  color: Color(0xFF059669),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Error Badge if 404 or mismatch
                    if (localError != null) ...[
                      Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: const Color(0xFFFEE2E2),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: const Color(0xFFFCA5A5)),
                        ),
                        child: Row(
                          children: [
                            const Icon(
                              Icons.error_outline_rounded,
                              color: Color(0xFFDC2626),
                              size: 18,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                localError!,
                                style: const TextStyle(
                                  color: Color(0xFF991B1B),
                                  fontWeight: FontWeight.w600,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],

                    // Input for Rack ID
                    const Text(
                      'Scanned Rack ID',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: Color(0xFF334155),
                      ),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: rackController,
                      decoration: InputDecoration(
                        hintText: 'e.g. ${step.rackId}',
                        prefixIcon: const Icon(Icons.grid_view_rounded, size: 20),
                        filled: true,
                        fillColor: const Color(0xFFF8FAFC),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),

                    // Input for SKU
                    const Text(
                      'Scanned Product SKU',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: Color(0xFF334155),
                      ),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: skuController,
                      decoration: InputDecoration(
                        hintText: 'e.g. ${step.sku}',
                        prefixIcon: const Icon(Icons.inventory_2_outlined, size: 20),
                        filled: true,
                        fillColor: const Color(0xFFF8FAFC),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),

                    // Scan Simulation Shortcuts
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            style: OutlinedButton.styleFrom(
                              foregroundColor: const Color(0xFF2563EB),
                              side: const BorderSide(color: Color(0xFF2563EB)),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                            icon: const Icon(Icons.auto_fix_high, size: 16),
                            label: const Text(
                              'Simulate Scan (Match)',
                              style: TextStyle(fontSize: 11),
                            ),
                            onPressed: () {
                              setModalState(() {
                                rackController.text = step.rackId;
                                skuController.text = step.sku;
                                localError = null;
                              });
                            },
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: OutlinedButton.icon(
                            style: OutlinedButton.styleFrom(
                              foregroundColor: const Color(0xFFDC2626),
                              side: const BorderSide(color: Color(0xFFFCA5A5)),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                            icon: const Icon(Icons.shuffle_rounded, size: 16),
                            label: const Text(
                              'Simulate Mismatch',
                              style: TextStyle(fontSize: 11),
                            ),
                            onPressed: () {
                              setModalState(() {
                                rackController.text = 'WRONG-RACK';
                                skuController.text = step.sku;
                                localError = null;
                              });
                            },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // Verify Button
                    SizedBox(
                      width: double.infinity,
                      height: 48,
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF0F172A),
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10),
                          ),
                        ),
                        onPressed: isVerifying
                            ? null
                            : () async {
                                final inputRack = rackController.text.trim();
                                final inputSku = skuController.text.trim();

                                if (inputRack.isEmpty || inputSku.isEmpty) {
                                  setModalState(() {
                                    localError = 'Please enter or scan both rack ID and SKU.';
                                  });
                                  return;
                                }

                                setModalState(() {
                                  isVerifying = true;
                                  localError = null;
                                });

                                final result =
                                    await _apiService.verifyBarcodeScan(
                                  inputSku,
                                  inputRack,
                                );

                                if (result.isVerified) {
                                  if (ctx.mounted) {
                                    Navigator.pop(ctx);
                                  }
                                  if (!mounted) return;

                                  setState(() {
                                    step.isCompleted = true;
                                    // Advance to next incomplete stop
                                    final nextIncomplete = _pickPath!.steps
                                        .indexWhere((s) => !s.isCompleted);
                                    if (nextIncomplete >= 0) {
                                      _activeStepIndex = nextIncomplete;
                                    }
                                  });

                                  ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                      content: Row(
                                        children: [
                                          const Icon(
                                            Icons.check_circle_rounded,
                                            color: Colors.white,
                                          ),
                                          const SizedBox(width: 8),
                                          Text(
                                            'Stop #${step.stepNumber} Verified! Pick confirmed.',
                                          ),
                                        ],
                                      ),
                                      backgroundColor: const Color(0xFF059669),
                                      behavior: SnackBarBehavior.floating,
                                    ),
                                  );

                                  if (_isOrderComplete) {
                                    _showOrderCompleteDialog();
                                  }
                                } else {
                                  setModalState(() {
                                    isVerifying = false;
                                    localError = result.errorMessage ??
                                        'Incorrect rack or SKU mismatch';
                                  });
                                }
                              },
                        child: isVerifying
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Text(
                                'Verify Scan & Pick',
                                style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  void _showOrderCompleteDialog() {
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Row(
          children: [
            Icon(Icons.emoji_events_rounded, color: Colors.amber, size: 28),
            SizedBox(width: 8),
            Text('Order Pick Complete!'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Order ${_pickPath?.orderNumber ?? ''} fulfilled!',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
            ),
            const SizedBox(height: 8),
            Text(
              'All ${_pickPath?.steps.length ?? 0} waypoint stops verified.\n'
              'Total 2-opt distance: ${_pickPath?.totalDistance.toStringAsFixed(1)}m '
              '(${_pickPath?.distanceSavingsPercent.toStringAsFixed(0)}% distance saved).',
              style: const TextStyle(fontSize: 13, color: Color(0xFF475569)),
            ),
          ],
        ),
        actions: [
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF0F172A),
              foregroundColor: Colors.white,
            ),
            onPressed: () {
              Navigator.pop(ctx);
              Navigator.pop(context); // Back to Home
            },
            child: const Text('Return to Home'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF8FAFC),
      appBar: AppBar(
        title: Text(
          _pickPath != null
              ? 'Pick Route: ${_pickPath!.orderNumber}'
              : 'Pick Path Navigation',
          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 17),
        ),
        actions: [
          IconButton(
            tooltip: 'Select Different Order',
            icon: const Icon(Icons.swap_horiz_rounded),
            onPressed: _openOrderSelectorDialog,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  CircularProgressIndicator(),
                  SizedBox(height: 12),
                  Text('Calculating 2-opt picking sequence...'),
                ],
              ),
            )
          : _errorMessage != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(
                          Icons.error_outline_rounded,
                          size: 48,
                          color: Color(0xFFDC2626),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          _errorMessage!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Color(0xFF475569)),
                        ),
                        const SizedBox(height: 16),
                        ElevatedButton.icon(
                          icon: const Icon(Icons.list_alt_rounded),
                          label: const Text('Select another order'),
                          onPressed: _openOrderSelectorDialog,
                        ),
                      ],
                    ),
                  ),
                )
              : _pickPath == null
                  ? _buildOrderSelectionList()
                  : _buildPickPathContent(),
    );
  }

  Widget _buildOrderSelectionList() {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Select Order to Pick',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.bold,
              color: Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Pick paths are available for orders approved by the warehouse manager.',
            style: TextStyle(fontSize: 13, color: Color(0xFF64748B)),
          ),
          const SizedBox(height: 16),
          Expanded(
            child: _availableOrders.isEmpty
                ? const Center(child: Text('No approved orders available.'))
                : ListView.builder(
                    itemCount: _availableOrders.length,
                    itemBuilder: (context, index) {
                      final order = _availableOrders[index];
                      return Card(
                        margin: const EdgeInsets.only(bottom: 10),
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                          side: BorderSide(color: Colors.grey.shade200),
                        ),
                        child: ListTile(
                          title: Text(
                            order.orderNumber,
                            style: const TextStyle(fontWeight: FontWeight.bold),
                          ),
                          subtitle: Text('Status: ${order.status} • ${order.itemCount} items'),
                          trailing: const Icon(Icons.arrow_forward_ios_rounded, size: 16),
                          onTap: () => _loadPickPath(order.id),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  void _openOrderSelectorDialog() {
    final controller = TextEditingController();
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Enter Order ID or Number'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            hintText: 'e.g. 1 or ORD-1001',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              _loadOrdersForSelection();
            },
            child: const Text('Browse List'),
          ),
          ElevatedButton(
            onPressed: () {
              final val = controller.text.trim();
              if (val.isNotEmpty) {
                Navigator.pop(ctx);
                _loadPickPath(val);
              }
            },
            child: const Text('Load Route'),
          ),
        ],
      ),
    );
  }

  Widget _buildPickPathContent() {
    final route = _pickPath!;
    final totalSteps = route.steps.length;

    return Column(
      children: [
        // 2-Opt Tour Metrics Summary Header
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF0F172A),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.1),
                blurRadius: 10,
                offset: const Offset(0, 4),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.amber.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.amber.withValues(alpha: 0.4)),
                    ),
                    child: const Text(
                      '2-OPT OPTIMIZED TOUR',
                      style: TextStyle(
                        color: Colors.amber,
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                  Text(
                    'Stop ${_activeStepIndex + 1} of $totalSteps',
                    style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // Optimization comparison metrics
              Row(
                children: [
                  _buildMetricTile(
                    'Optimized Distance',
                    '${route.totalDistance.toStringAsFixed(1)}m',
                    Colors.white,
                  ),
                  _buildMetricTile(
                    'Baseline (FIFO)',
                    '${route.baselineDistance.toStringAsFixed(1)}m',
                    Colors.white70,
                  ),
                  _buildMetricTile(
                    'Distance Saved',
                    '${route.distanceSavingsPercent.toStringAsFixed(0)}%',
                    const Color(0xFF34D399),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // Stepper Progress Bar
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: totalSteps > 0 ? _completedCount / totalSteps : 0.0,
                  backgroundColor: Colors.white24,
                  valueColor: const AlwaysStoppedAnimation<Color>(Color(0xFF10B981)),
                  minHeight: 6,
                ),
              ),
            ],
          ),
        ),

        // Waypoints Stops Stepper List
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: route.steps.length,
            itemBuilder: (context, index) {
              final step = route.steps[index];
              final isCurrent = index == _activeStepIndex && !step.isCompleted;

              return Container(
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(
                    color: step.isCompleted
                        ? const Color(0xFF059669)
                        : isCurrent
                            ? const Color(0xFF2563EB)
                            : Colors.grey.shade200,
                    width: isCurrent ? 2 : 1,
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: isCurrent ? 0.06 : 0.02),
                      blurRadius: 10,
                      offset: const Offset(0, 4),
                    ),
                  ],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Step Header Row
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Row(
                          children: [
                            CircleAvatar(
                              radius: 14,
                              backgroundColor: step.isCompleted
                                  ? const Color(0xFF059669)
                                  : isCurrent
                                      ? const Color(0xFF2563EB)
                                      : Colors.grey.shade300,
                              child: step.isCompleted
                                  ? const Icon(
                                      Icons.check,
                                      size: 16,
                                      color: Colors.white,
                                    )
                                  : Text(
                                      '${step.stepNumber}',
                                      style: TextStyle(
                                        color: isCurrent
                                            ? Colors.white
                                            : Colors.grey.shade700,
                                        fontSize: 12,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                            ),
                            const SizedBox(width: 10),
                            Text(
                              'Rack ${step.rackId}',
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                fontSize: 16,
                                color: Color(0xFF0F172A),
                              ),
                            ),
                          ],
                        ),

                        // Status Badge
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: step.isCompleted
                                ? const Color(0xFFDCFCE7)
                                : isCurrent
                                    ? const Color(0xFFDBEAFE)
                                    : const Color(0xFFF1F5F9),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            step.isCompleted
                                ? 'PICKED'
                                : isCurrent
                                    ? 'NEXT STOP'
                                    : 'PENDING',
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.bold,
                              color: step.isCompleted
                                  ? const Color(0xFF166534)
                                  : isCurrent
                                      ? const Color(0xFF1E40AF)
                                      : const Color(0xFF64748B),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),

                    // Coordinates & Location details
                    Row(
                      children: [
                        const Icon(
                          Icons.location_on_outlined,
                          size: 15,
                          color: Color(0xFF64748B),
                        ),
                        const SizedBox(width: 4),
                        Text(
                          'Zone ${step.zone} • Coordinates (${step.xCoord.toStringAsFixed(1)}, ${step.yCoord.toStringAsFixed(1)})',
                          style: const TextStyle(
                            fontSize: 12,
                            color: Color(0xFF64748B),
                          ),
                        ),
                      ],
                    ),
                    const Divider(height: 18),

                    // Product & Quantity to Pick
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                step.productName.isNotEmpty
                                    ? step.productName
                                    : 'SKU ${step.sku}',
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                  fontSize: 14,
                                  color: Color(0xFF1E293B),
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                'Batch: ${step.batchNumber}',
                                style: const TextStyle(
                                  fontSize: 11,
                                  fontFamily: 'monospace',
                                  color: Color(0xFF64748B),
                                ),
                              ),
                            ],
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFEF3C7),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            'Pick: ${step.quantityToPick} units',
                            style: const TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 12,
                              color: Color(0xFF92400E),
                            ),
                          ),
                        ),
                      ],
                    ),

                    // Barcode Verification Action
                    if (!step.isCompleted) ...[
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          style: ElevatedButton.styleFrom(
                            backgroundColor: isCurrent
                                ? const Color(0xFF2563EB)
                                : const Color(0xFF0F172A),
                            foregroundColor: Colors.white,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                          icon: const Icon(
                            Icons.qr_code_scanner_rounded,
                            size: 18,
                          ),
                          label: Text(
                            isCurrent
                                ? 'Scan & Verify Stop #${step.stepNumber}'
                                : 'Verify Stop #${step.stepNumber}',
                            style: const TextStyle(fontSize: 13),
                          ),
                          onPressed: () => _openBarcodeVerification(step),
                        ),
                      ),
                    ],
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildMetricTile(String label, String value, Color valueColor) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(color: Colors.white60, fontSize: 11),
          ),
          const SizedBox(height: 2),
          Text(
            value,
            style: TextStyle(
              color: valueColor,
              fontWeight: FontWeight.bold,
              fontSize: 15,
            ),
          ),
        ],
      ),
    );
  }
}
