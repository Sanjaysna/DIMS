import 'package:flutter/foundation.dart';
import 'package:jwt_decoder/jwt_decoder.dart';
import '../models/auth_tokens.dart';
import '../models/user_profile.dart';
import '../services/auth_service.dart';

enum AuthStatus {
  initial,
  authenticating,
  authenticated,
  unauthenticated,
  error,
}

class AuthProvider with ChangeNotifier {
  final AuthService _authService;

  AuthStatus _status = AuthStatus.initial;
  String? _accessToken;
  String? _refreshToken;
  UserProfile? _userProfile;
  String? _errorMessage;

  AuthProvider({AuthService? authService})
      : _authService = authService ?? AuthService();

  // Getters
  AuthStatus get status => _status;
  bool get isLoading => _status == AuthStatus.authenticating;
  bool get isAuthenticated => _status == AuthStatus.authenticated;
  String? get accessToken => _accessToken;
  String? get refreshToken => _refreshToken;
  UserProfile? get userProfile => _userProfile;
  String? get userRole => _userProfile?.role;
  String? get errorMessage => _errorMessage;

  /// Attempts to authenticate with the backend using credentials
  Future<bool> login({
    required String username,
    required String password,
  }) async {
    _status = AuthStatus.authenticating;
    _errorMessage = null;
    notifyListeners();

    try {
      final AuthTokens tokens = await _authService.login(
        username: username,
        password: password,
      );

      _accessToken = tokens.access;
      _refreshToken = tokens.refresh;

      // Decode the JWT to construct the UserProfile
      final payload = JwtDecoder.decode(tokens.access);
      _userProfile = UserProfile.fromJwtPayload(payload);

      _status = AuthStatus.authenticated;
      _errorMessage = null;
      notifyListeners();
      return true;
    } catch (e) {
      _status = AuthStatus.error;
      _errorMessage = e.toString().replaceFirst('Exception: ', '');
      notifyListeners();
      return false;
    }
  }

  /// Restores session on app startup if a valid token is found
  Future<void> checkAuthStatus() async {
    final token = await _authService.getAccessToken();
    if (token != null && !JwtDecoder.isExpired(token)) {
      _accessToken = token;
      _refreshToken = await _authService.getRefreshToken();
      final payload = JwtDecoder.decode(token);
      _userProfile = UserProfile.fromJwtPayload(payload);
      _status = AuthStatus.authenticated;
    } else {
      _status = AuthStatus.unauthenticated;
    }
    notifyListeners();
  }

  /// Clears user credentials and resets state
  Future<void> logout() async {
    await _authService.logout();
    _accessToken = null;
    _refreshToken = null;
    _userProfile = null;
    _errorMessage = null;
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  void clearError() {
    if (_errorMessage != null) {
      _errorMessage = null;
      notifyListeners();
    }
  }
}
