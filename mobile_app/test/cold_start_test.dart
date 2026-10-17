import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mobile_app/utils/cold_start_http.dart';

void main() {
  group('ColdStartHttpClient Tests', () {
    test('successful request returns response without error', () async {
      final mockClient = MockClient((request) async {
        return http.Response('{"status": "ok"}', 200);
      });

      final response = await ColdStartHttpClient.get(
        Uri.parse('https://example.com/test'),
        client: mockClient,
      );

      expect(response.statusCode, 200);
      expect(response.body, '{"status": "ok"}');
    });

    test('retries on 502 Bad Gateway and surfaces wake up message', () async {
      int callCount = 0;
      final statusMessages = <String>[];

      final mockClient = MockClient((request) async {
        callCount++;
        if (callCount == 1) {
          return http.Response('Bad Gateway (Server starting)', 502);
        }
        return http.Response('{"status": "ready"}', 200);
      });

      final response = await ColdStartHttpClient.post(
        Uri.parse('https://example.com/api/login'),
        client: mockClient,
        onStatusChange: (msg) => statusMessages.add(msg),
      );

      expect(callCount, 2);
      expect(response.statusCode, 200);
      expect(response.body, '{"status": "ready"}');
      expect(statusMessages, contains(ColdStartHttpClient.wakeUpMessage));
    });

    test('retries on TimeoutException and surfaces wake up message', () async {
      int callCount = 0;
      final statusMessages = <String>[];

      final mockClient = MockClient((request) async {
        callCount++;
        if (callCount == 1) {
          // Trigger timeout
          await Future.delayed(const Duration(milliseconds: 100));
          return http.Response('OK', 200);
        }
        return http.Response('{"result": "success"}', 200);
      });

      final response = await ColdStartHttpClient.get(
        Uri.parse('https://example.com/data'),
        client: mockClient,
        timeout: const Duration(milliseconds: 40),
        onStatusChange: (msg) => statusMessages.add(msg),
      );

      expect(callCount, 2);
      expect(response.statusCode, 200);
      expect(statusMessages, contains(ColdStartHttpClient.wakeUpMessage));
    });
  });
}
