import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:jwt_decoder/jwt_decoder.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/auth_tokens.dart';

class AuthService {
  // 10.0.2.2 is the Android emulator's alias for the host machine's 127.0.0.1
  static const String defaultTokenUrl = 'http://10.0.2.2:8000/api/token/';
  static const String defaultRefreshUrl = 'http://10.0.2.2:8000/api/token/refresh/';

  // Keys used for SharedPreferences persistence
  static const String keyAccessToken = 'access_token';
  static const String keyRefreshToken = 'refresh_token';

  final String tokenUrl;
  final String refreshUrl;
  final http.Client _client;

  AuthService({
    this.tokenUrl = defaultTokenUrl,
    this.refreshUrl = defaultRefreshUrl,
    http.Client? client,
  }) : _client = client ?? http.Client();

  /// Authenticates with the backend by POSTing credentials to /api/token/
  /// Extracts and persists access and refresh tokens via SharedPreferences.
  Future<AuthTokens> login({
    required String username,
    required String password,
  }) async {
    final cleanUsername = username.trim();
    final cleanPassword = password;

    if (cleanUsername.isEmpty || cleanPassword.isEmpty) {
      throw Exception('Username and password cannot be empty.');
    }

    try {
      final response = await http.post(
        Uri.parse('http://10.0.2.2:8000/api/token/'),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: jsonEncode({
          // Django auth.User uses USERNAME_FIELD = 'username'
          'username': cleanUsername,
          'password': cleanPassword,
        }),
      );

      if (response.statusCode == 200) {
        final Map<String, dynamic> data = jsonDecode(response.body);

        final String? accessToken = data['access'];
        final String? refreshToken = data['refresh'];

        if (accessToken == null || refreshToken == null) {
          throw const FormatException('Tokens missing from server response.');
        }

        // Save tokens in SharedPreferences
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString(keyAccessToken, accessToken);
        await prefs.setString(keyRefreshToken, refreshToken);

        return AuthTokens(
          access: accessToken,
          refresh: refreshToken,
        );
      } else if (response.statusCode == 401) {
        final data = _safeDecodeJson(response.body);
        final detail = data?['detail'] ?? 'Invalid username or password.';
        throw Exception(detail);
      } else if (response.statusCode == 400) {
        final data = _safeDecodeJson(response.body);
        final error = data?['detail'] ??
            data?['username']?[0] ??
            data?['password']?[0] ??
            data?['non_field_errors']?[0] ??
            'Malformed login request or missing credentials (400 Bad Request).';
        throw Exception(error);
      } else {
        final data = _safeDecodeJson(response.body);
        final detail = data?['detail'] ??
            data?['non_field_errors']?[0] ??
            'Authentication failed with status code ${response.statusCode}';
        throw Exception(detail);
      }
    } on SocketException {
      throw Exception(
        'Unable to connect to http://10.0.2.2:8000/api/token/. Ensure the Django server is running on port 8000.',
      );
    } on http.ClientException catch (e) {
      throw Exception('Network error: ${e.message}');
    } catch (e) {
      if (e is FormatException) {
        throw Exception('Server returned invalid response format.');
      }
      rethrow;
    }
  }

  /// Refreshes the access token using the stored refresh token
  Future<String?> refreshToken() async {
    final currentRefreshToken = await getRefreshToken();
    if (currentRefreshToken == null || JwtDecoder.isExpired(currentRefreshToken)) {
      await logout();
      return null;
    }

    try {
      final response = await _client.post(
        Uri.parse(refreshUrl),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh': currentRefreshToken}),
      );

      if (response.statusCode == 200) {
        final Map<String, dynamic> data = jsonDecode(response.body);
        final String? newAccessToken = data['access'];
        if (newAccessToken != null) {
          final prefs = await SharedPreferences.getInstance();
          await prefs.setString(keyAccessToken, newAccessToken);
          return newAccessToken;
        }
      }
    } catch (_) {
      // Refresh failed
    }
    return null;
  }

  /// Retrieves the persisted access token
  Future<String?> getAccessToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(keyAccessToken);
  }

  /// Retrieves the persisted refresh token
  Future<String?> getRefreshToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(keyRefreshToken);
  }

  /// Decodes token payload into a Map
  Map<String, dynamic>? decodeToken(String token) {
    try {
      return JwtDecoder.decode(token);
    } catch (_) {
      return null;
    }
  }

  /// Checks if the current access token exists and is valid
  Future<bool> isAuthenticated() async {
    final token = await getAccessToken();
    if (token == null) return false;
    return !JwtDecoder.isExpired(token);
  }

  /// Extracts user role or user claims from the current access token
  Future<String> getUserRole() async {
    final token = await getAccessToken();
    if (token == null) return 'Guest';

    try {
      final payload = JwtDecoder.decode(token);
      final role = payload['role'] ??
          payload['user_role'] ??
          payload['group'] ??
          (payload['is_superuser'] == true ? 'Administrator' : 'Warehouse Staff');
      return role.toString();
    } catch (_) {
      return 'Warehouse Staff';
    }
  }

  /// Clears stored tokens on user logout
  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(keyAccessToken);
    await prefs.remove(keyRefreshToken);
  }

  Map<String, dynamic>? _safeDecodeJson(String source) {
    try {
      return jsonDecode(source) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }
}
