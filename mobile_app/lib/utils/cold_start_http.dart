import 'dart:async';
import 'dart:io';
import 'package:http/http.dart' as http;

/// Robust HTTP utility that handles Render free-tier cold-starts and session lifecycle.
/// Raises timeout to 60s, automatically retries on network drops/502/503/504,
/// surfaces a friendly "Waking up the server, please wait..." status message,
/// and delegates 401 Unauthorized responses to a central session handler.
class ColdStartHttpClient {
  static const Duration defaultTimeout = Duration(seconds: 60);
  static const Duration wakeUpNoticeThreshold = Duration(milliseconds: 2500);
  static const String wakeUpMessage = 'Waking up the server, please wait...';

  /// Callback triggered when an API response returns 401 Unauthorized (session expired).
  static void Function(String message)? onUnauthorized;

  /// Execute an HTTP GET request with cold-start resilience.
  static Future<http.Response> get(
    Uri uri, {
    Map<String, String>? headers,
    void Function(String message)? onStatusChange,
    int maxRetries = 2,
    Duration timeout = defaultTimeout,
    http.Client? client,
    bool notifyOnUnauthorized = true,
  }) {
    return _sendWithRetry(
      () {
        final c = client ?? http.Client();
        return c.get(uri, headers: headers);
      },
      onStatusChange: onStatusChange,
      maxRetries: maxRetries,
      timeout: timeout,
      notifyOnUnauthorized: notifyOnUnauthorized,
    );
  }

  /// Execute an HTTP POST request with cold-start resilience.
  static Future<http.Response> post(
    Uri uri, {
    Map<String, String>? headers,
    Object? body,
    void Function(String message)? onStatusChange,
    int maxRetries = 2,
    Duration timeout = defaultTimeout,
    http.Client? client,
    bool notifyOnUnauthorized = true,
  }) {
    return _sendWithRetry(
      () {
        final c = client ?? http.Client();
        return c.post(uri, headers: headers, body: body);
      },
      onStatusChange: onStatusChange,
      maxRetries: maxRetries,
      timeout: timeout,
      notifyOnUnauthorized: notifyOnUnauthorized,
    );
  }

  /// Execute an HTTP PUT request with cold-start resilience.
  static Future<http.Response> put(
    Uri uri, {
    Map<String, String>? headers,
    Object? body,
    void Function(String message)? onStatusChange,
    int maxRetries = 2,
    Duration timeout = defaultTimeout,
    http.Client? client,
    bool notifyOnUnauthorized = true,
  }) {
    return _sendWithRetry(
      () {
        final c = client ?? http.Client();
        return c.put(uri, headers: headers, body: body);
      },
      onStatusChange: onStatusChange,
      maxRetries: maxRetries,
      timeout: timeout,
      notifyOnUnauthorized: notifyOnUnauthorized,
    );
  }

  /// Execute an HTTP DELETE request with cold-start resilience.
  static Future<http.Response> delete(
    Uri uri, {
    Map<String, String>? headers,
    Object? body,
    void Function(String message)? onStatusChange,
    int maxRetries = 2,
    Duration timeout = defaultTimeout,
    http.Client? client,
    bool notifyOnUnauthorized = true,
  }) {
    return _sendWithRetry(
      () {
        final c = client ?? http.Client();
        return c.delete(uri, headers: headers, body: body);
      },
      onStatusChange: onStatusChange,
      maxRetries: maxRetries,
      timeout: timeout,
      notifyOnUnauthorized: notifyOnUnauthorized,
    );
  }

  /// Internal retry orchestration with timeout and status notification.
  static Future<http.Response> _sendWithRetry(
    Future<http.Response> Function() requestFn, {
    void Function(String message)? onStatusChange,
    required int maxRetries,
    required Duration timeout,
    Duration retryDelay = const Duration(seconds: 2),
    bool notifyOnUnauthorized = true,
  }) async {
    int attempts = 0;
    while (true) {
      attempts++;
      Timer? noticeTimer;

      try {
        if (onStatusChange != null) {
          noticeTimer = Timer(wakeUpNoticeThreshold, () {
            onStatusChange(wakeUpMessage);
          });
        }

        final response = await requestFn().timeout(timeout);
        noticeTimer?.cancel();

        // 502 Bad Gateway / 503 Service Unavailable / 504 Gateway Timeout
        // are standard Render indicators that the backend container is still booting.
        final isServerStarting = response.statusCode == 502 ||
            response.statusCode == 503 ||
            response.statusCode == 504;

        if (isServerStarting && attempts <= maxRetries) {
          onStatusChange?.call(wakeUpMessage);
          await Future.delayed(retryDelay);
          continue;
        }

        // 401 Unauthorized indicates an expired or invalidated session
        if (response.statusCode == 401 && notifyOnUnauthorized) {
          onUnauthorized?.call('Session expired. Please log in again.');
        }

        return response;
      } on TimeoutException {
        noticeTimer?.cancel();
        if (attempts <= maxRetries) {
          onStatusChange?.call(wakeUpMessage);
          await Future.delayed(retryDelay);
          continue;
        }
        rethrow;
      } on SocketException {
        noticeTimer?.cancel();
        if (attempts <= maxRetries) {
          onStatusChange?.call(wakeUpMessage);
          await Future.delayed(retryDelay);
          continue;
        }
        rethrow;
      } on http.ClientException {
        noticeTimer?.cancel();
        if (attempts <= maxRetries) {
          onStatusChange?.call(wakeUpMessage);
          await Future.delayed(retryDelay);
          continue;
        }
        rethrow;
      } catch (e) {
        noticeTimer?.cancel();
        if (attempts <= maxRetries &&
            (e.toString().contains('Failed host lookup') ||
                e.toString().contains('Connection refused'))) {
          onStatusChange?.call(wakeUpMessage);
          await Future.delayed(retryDelay);
          continue;
        }
        rethrow;
      }
    }
  }
}
