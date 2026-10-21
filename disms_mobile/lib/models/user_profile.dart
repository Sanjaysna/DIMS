class UserProfile {
  final int? userId;
  final String? username;
  final String? email;
  final String role;
  final Map<String, dynamic> rawPayload;

  UserProfile({
    this.userId,
    this.username,
    this.email,
    required this.role,
    required this.rawPayload,
  });

  factory UserProfile.fromJwtPayload(Map<String, dynamic> payload) {
    // Extract role from common JWT claim keys or fallback to default
    final role = payload['role'] ??
        payload['user_role'] ??
        payload['group'] ??
        (payload['is_superuser'] == true ? 'Administrator' : 'Warehouse Staff');

    return UserProfile(
      userId: payload['user_id'] is int
          ? payload['user_id'] as int
          : int.tryParse(payload['user_id']?.toString() ?? ''),
      username: payload['username']?.toString(),
      email: payload['email']?.toString(),
      role: role.toString(),
      rawPayload: payload,
    );
  }
}
