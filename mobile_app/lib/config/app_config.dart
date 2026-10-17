class AppConfig {
  AppConfig._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://school-bus-tracker-crwb.onrender.com',
  );

  static Uri get authLoginUri => Uri.parse('$apiBaseUrl/api/v1/auth/login');

  static Uri get authForgotPasswordUri =>
      Uri.parse('$apiBaseUrl/api/v1/auth/forgot-password');

  static Uri get authResetPasswordUri =>
      Uri.parse('$apiBaseUrl/api/v1/auth/reset-password');

  static Uri get authMeUri => Uri.parse('$apiBaseUrl/api/v1/auth/me');

  static Uri get busesUri => Uri.parse('$apiBaseUrl/api/v1/buses');

  static Uri get studentsUri => Uri.parse('$apiBaseUrl/api/v1/students');

  static Uri get routesUri => Uri.parse('$apiBaseUrl/api/v1/routes');

  static Uri get driversUri => Uri.parse('$apiBaseUrl/api/v1/drivers');

  static Uri get attendanceUri => Uri.parse('$apiBaseUrl/api/v1/attendance');

  static Uri get notificationsRegisterTokenUri =>
      Uri.parse('$apiBaseUrl/api/v1/notifications/register-token');

  static Uri get notificationsUnregisterTokenUri =>
      Uri.parse('$apiBaseUrl/api/v1/notifications/unregister-token');

  static Uri get notificationsLogsUri =>
      Uri.parse('$apiBaseUrl/api/v1/notifications/logs');

  static Uri get routeChangeRequestsUri =>
      Uri.parse('$apiBaseUrl/api/v1/route-change-requests');

  static Uri studentById(String id) =>
      Uri.parse('$apiBaseUrl/api/v1/students/$id');

  static Uri routeById(String id) =>
      Uri.parse('$apiBaseUrl/api/v1/routes/$id');

  static Uri driverById(String id) =>
      Uri.parse('$apiBaseUrl/api/v1/drivers/$id');

  static Uri attendanceById(String id) =>
      Uri.parse('$apiBaseUrl/api/v1/attendance/$id');

  static Uri gpsUriForBus(String busId) =>
      Uri.parse('$apiBaseUrl/api/v1/buses/$busId/gps');

  static Uri routeChangeRequestById(String id) =>
      Uri.parse('$apiBaseUrl/api/v1/route-change-requests/$id');

  static Uri routeChangeRequestApprove(String id) =>
      Uri.parse('$apiBaseUrl/api/v1/route-change-requests/$id/approve');

  static Uri routeChangeRequestReject(String id) =>
      Uri.parse('$apiBaseUrl/api/v1/route-change-requests/$id/reject');

  static Uri routeChangeRequestCancel(String id) =>
      Uri.parse('$apiBaseUrl/api/v1/route-change-requests/$id/cancel');

  static Uri busLatestGps(String busId) =>
      Uri.parse('$apiBaseUrl/api/v1/buses/$busId/gps/latest');
}

