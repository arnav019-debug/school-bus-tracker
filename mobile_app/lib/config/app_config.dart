class AppConfig {
  AppConfig._();

  static const String apiBaseUrl =
      'https://school-bus-tracker-crwb.onrender.com';

  static Uri get authLoginUri => Uri.parse('$apiBaseUrl/api/v1/auth/login');

  static Uri get authMeUri => Uri.parse('$apiBaseUrl/api/v1/auth/me');

  static Uri get busesUri => Uri.parse('$apiBaseUrl/api/v1/buses');

  static Uri gpsUriForBus(String busId) =>
      Uri.parse('$apiBaseUrl/api/v1/buses/$busId/gps');
}
