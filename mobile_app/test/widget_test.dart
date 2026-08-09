import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_app/main.dart';

void main() {
  testWidgets('app opens to the login screen', (WidgetTester tester) async {
    await tester.pumpWidget(const SchoolBusTrackerApp());

    expect(find.text('School Bus Tracker'), findsOneWidget);
    expect(find.text('Sign in'), findsOneWidget);
  });
}
