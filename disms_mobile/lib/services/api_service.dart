import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/order_models.dart';
import '../models/product.dart';
import 'auth_service.dart';

class ApiService {
  static const String defaultBaseUrl = 'http://10.0.2.2:8000/api';

  final String baseUrl;
  final http.Client _client;
  final AuthService _authService;

  ApiService({
    this.baseUrl = defaultBaseUrl,
    http.Client? client,
    AuthService? authService,
  })  : _client = client ?? http.Client(),
        _authService = authService ?? AuthService();

  /// Retrieves the current active JWT access token from persistent storage
  Future<String?> _getAccessToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(AuthService.keyAccessToken);
  }

  /// Builds authorization headers, injecting `Authorization: Bearer <token>`
  Future<Map<String, String>> _buildHeaders({bool includeAuth = true}) async {
    final headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };

    if (includeAuth) {
      final token = await _getAccessToken();
      if (token != null && token.isNotEmpty) {
        headers['Authorization'] = 'Bearer $token';
      }
    }
    return headers;
  }

  /// Authenticated GET helper with optional automatic 401 retry on token refresh
  Future<http.Response> get(String endpoint, {bool requiresAuth = true}) async {
    final uri = Uri.parse('$baseUrl$endpoint');
    var headers = await _buildHeaders(includeAuth: requiresAuth);

    try {
      var response = await _client
          .get(uri, headers: headers)
          .timeout(const Duration(seconds: 15));

      // Handle token expiration & retry once
      if (response.statusCode == 401 && requiresAuth) {
        final refreshed = await _authService.refreshToken();
        if (refreshed != null) {
          headers = await _buildHeaders(includeAuth: true);
          response = await _client
              .get(uri, headers: headers)
              .timeout(const Duration(seconds: 15));
        }
      }

      return response;
    } on SocketException {
      throw Exception(
        'Unable to connect to server at $uri. Ensure Django backend is running.',
      );
    }
  }

  /// Authenticated POST helper with optional automatic 401 retry on token refresh
  Future<http.Response> post(
    String endpoint, {
    Map<String, dynamic>? body,
    bool requiresAuth = true,
  }) async {
    final uri = Uri.parse('$baseUrl$endpoint');
    var headers = await _buildHeaders(includeAuth: requiresAuth);
    final encodedBody = body != null ? jsonEncode(body) : null;

    try {
      var response = await _client
          .post(uri, headers: headers, body: encodedBody)
          .timeout(const Duration(seconds: 15));

      // Handle token expiration & retry once
      if (response.statusCode == 401 && requiresAuth) {
        final refreshed = await _authService.refreshToken();
        if (refreshed != null) {
          headers = await _buildHeaders(includeAuth: true);
          response = await _client
              .post(uri, headers: headers, body: encodedBody)
              .timeout(const Duration(seconds: 15));
        }
      }

      return response;
    } on SocketException {
      throw Exception(
        'Unable to connect to server at $uri. Ensure Django backend is running.',
      );
    }
  }

  /// GET /api/v1/products/
  /// Fetches available product catalogue with current batch stocks
  Future<List<ProductItem>> fetchProducts() async {
    final response = await get('/v1/products/');

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data
          .map((item) => ProductItem.fromJson(item as Map<String, dynamic>))
          .toList();
    } else {
      final message = _parseErrorMessage(response.body, response.statusCode);
      throw Exception('Failed to fetch products: $message');
    }
  }

  /// POST /api/v1/orders/
  /// Creates a new order with items in 'pending_approval' status
  Future<OrderCreateResponse> createOrder(Map<String, dynamic> payload) async {
    final response = await post('/v1/orders/', body: payload);

    if (response.statusCode == 201 || response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return OrderCreateResponse.fromJson(data);
    } else {
      final message = _parseErrorMessage(response.body, response.statusCode);
      throw Exception(message);
    }
  }

  /// GET /api/v1/orders/
  /// Retrieves list of existing orders for picker selection
  Future<List<OrderSummary>> fetchOrders() async {
    final response = await get('/v1/orders/');

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data
          .map((item) => OrderSummary.fromJson(item as Map<String, dynamic>))
          .toList();
    } else {
      final message = _parseErrorMessage(response.body, response.statusCode);
      throw Exception('Failed to fetch orders: $message');
    }
  }

  /// `GET /api/v1/orders/<orderId>/pick-path/`
  /// Retrieves optimized 2-opt pick route for an approved order
  Future<PickPathResponse> fetchPickPath(dynamic orderId) async {
    final response = await get('/v1/orders/$orderId/pick-path/');

    if (response.statusCode == 200) {
      final Map<String, dynamic> data = jsonDecode(response.body);
      return PickPathResponse.fromJson(data);
    } else {
      final message = _parseErrorMessage(response.body, response.statusCode);
      throw Exception(message);
    }
  }

  /// POST /api/v1/inventory/scan/
  /// Verifies barcode / QR scan matching SKU and rack_id
  Future<ScanVerificationResult> verifyBarcodeScan(
    String sku,
    String rackId,
  ) async {
    final payload = {
      'sku': sku.trim(),
      'rack_id': rackId.trim(),
    };

    final response = await post('/v1/inventory/scan/', body: payload);

    if (response.statusCode == 200) {
      return ScanVerificationResult(
        isVerified: true,
        sku: sku,
        rackId: rackId,
      );
    } else if (response.statusCode == 404) {
      return ScanVerificationResult(
        isVerified: false,
        errorMessage: 'Incorrect rack or SKU mismatch',
        sku: sku,
        rackId: rackId,
      );
    } else {
      final errorMsg = _parseErrorMessage(
        response.body,
        response.statusCode,
        defaultMsg: 'Verification failed for $sku on $rackId',
      );
      return ScanVerificationResult(
        isVerified: false,
        errorMessage: errorMsg,
        sku: sku,
        rackId: rackId,
      );
    }
  }

  String _parseErrorMessage(
    String responseBody,
    int statusCode, {
    String? defaultMsg,
  }) {
    try {
      final Map<String, dynamic> json = jsonDecode(responseBody);
      return json['error'] ??
          json['detail'] ??
          json['message'] ??
          defaultMsg ??
          'Request failed with status $statusCode';
    } catch (_) {
      return defaultMsg ?? 'Server returned HTTP $statusCode';
    }
  }
}
