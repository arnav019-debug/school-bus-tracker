import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_app/main.dart';

const MethodChannel _secureStorageChannel = MethodChannel(
  'plugins.it_nomads.com/flutter_secure_storage',
);

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      _secureStorageChannel,
      (call) async {
        switch (call.method) {
          case 'read':
            return null;
          case 'readAll':
            return <String, String>{};
          case 'write':
          case 'delete':
          case 'deleteAll':
          case 'containsKey':
            return null;
          default:
            return null;
        }
      },
    );
  });

  tearDown(() {
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      _secureStorageChannel,
      null,
    );
  });

  testWidgets('app opens to the login screen', (WidgetTester tester) async {
    await tester.pumpWidget(const SchoolBusTrackerApp());
    await tester.pumpAndSettle();

    expect(find.text('School Bus Tracker'), findsOneWidget);
    expect(find.text('Sign in'), findsOneWidget);
  });
}
