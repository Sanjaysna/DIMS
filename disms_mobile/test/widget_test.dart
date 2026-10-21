import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:disms_mobile/main.dart';
import 'package:disms_mobile/models/order_models.dart';
import 'package:disms_mobile/models/product.dart';
import 'package:disms_mobile/screens/order_create_screen.dart';
import 'package:disms_mobile/screens/pick_path_screen.dart';
import 'package:disms_mobile/screens/home_screen.dart';
import 'package:disms_mobile/providers/auth_provider.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('DiSMSApp renders LoginScreen smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const DiSMSApp());
    await tester.pumpAndSettle();

    expect(find.text('DiSMS Mobile'), findsWidgets);
    expect(find.text('Sign In'), findsWidgets);
    expect(find.text('Username'), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
    expect(find.text('Demo Field Staff'), findsOneWidget);
    expect(find.text('Demo Picker'), findsOneWidget);
    expect(find.text('Demo Admin'), findsNothing);
  });

  testWidgets('OrderCreateScreen renders properly', (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: OrderCreateScreen(),
      ),
    );
    // Allow initial load
    await tester.pump();

    expect(find.text('Create Order'), findsOneWidget);
  });

  testWidgets('PickPathScreen renders properly', (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: PickPathScreen(),
      ),
    );
    await tester.pump();

    expect(find.text('Pick Path Navigation'), findsOneWidget);
  });

  test('OrderItemEntry correctly calculates inventory shortfall', () {
    final product = ProductItem(
      sku: 'SKU-TEST-1',
      name: 'Test Widget',
      description: 'A test product',
      availableStock: 5,
      batches: [],
    );

    final itemSufficient = OrderItemEntry(product: product, quantity: 4);
    expect(itemSufficient.hasShortfall, isFalse);
    expect(itemSufficient.shortfallAmount, equals(0));

    final itemExact = OrderItemEntry(product: product, quantity: 5);
    expect(itemExact.hasShortfall, isFalse);
    expect(itemExact.shortfallAmount, equals(0));

    final itemShortfall = OrderItemEntry(product: product, quantity: 8);
    expect(itemShortfall.hasShortfall, isTrue);
    expect(itemShortfall.shortfallAmount, equals(3));
  });

  test('PickPathResponse decodes JSON correctly', () {
    final json = {
      'order_id': 42,
      'order_number': 'ORD-42',
      'order_status': 'approved',
      'total_distance': 15.5,
      'baseline_distance': 25.0,
      'distance_savings_meters': 9.5,
      'distance_savings_percent': 38.0,
      'total_steps': 1,
      'steps': [
        {
          'step_number': 1,
          'rack_id': 'R-01',
          'zone': 'A',
          'x_coord': 1.0,
          'y_coord': 2.0,
          'batch_number': 'BATCH-1',
          'sku': 'SKU-1',
          'product_name': 'Widget A',
          'quantity_to_pick': 3,
        }
      ]
    };

    final pickPath = PickPathResponse.fromJson(json);
    expect(pickPath.orderId, equals(42));
    expect(pickPath.orderNumber, equals('ORD-42'));
    expect(pickPath.totalDistance, equals(15.5));
    expect(pickPath.steps.length, equals(1));
    expect(pickPath.steps.first.rackId, equals('R-01'));
    expect(pickPath.steps.first.isCompleted, isFalse);
  });

  testWidgets('HomeScreen Admin view displays restricted message and no operational cards', (WidgetTester tester) async {
    final authProvider = AuthProvider();
    await tester.pumpWidget(
      ChangeNotifierProvider<AuthProvider>.value(
        value: authProvider,
        child: const MaterialApp(
          home: HomeScreen(
            userRole: 'Admin',
            decodedToken: {'username': 'admin', 'is_superuser': true},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Access Restricted'), findsOneWidget);
    expect(find.text('Administrator access is restricted to the Web Dashboard.'), findsOneWidget);
    expect(find.text('Logout'), findsWidgets);
    expect(find.text('Create Order'), findsNothing);
    expect(find.text('Order Pick Path'), findsNothing);
  });

  testWidgets('HomeScreen Field Staff view displays only Create Order card', (WidgetTester tester) async {
    final authProvider = AuthProvider();
    await tester.pumpWidget(
      ChangeNotifierProvider<AuthProvider>.value(
        value: authProvider,
        child: const MaterialApp(
          home: HomeScreen(
            userRole: 'Field Staff',
            decodedToken: {'username': 'fieldstaff1'},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Create Order'), findsOneWidget);
    expect(find.text('Order Pick Path'), findsNothing);
    expect(find.text('Inventory Scan'), findsNothing);
    expect(find.text('Administrator access is restricted to the Web Dashboard.'), findsNothing);
  });

  testWidgets('HomeScreen Picker view displays only Order Pick Path and Inventory Scan', (WidgetTester tester) async {
    final authProvider = AuthProvider();
    await tester.pumpWidget(
      ChangeNotifierProvider<AuthProvider>.value(
        value: authProvider,
        child: const MaterialApp(
          home: HomeScreen(
            userRole: 'Picker',
            decodedToken: {'username': 'picker1'},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Order Pick Path'), findsOneWidget);
    expect(find.text('Inventory Scan'), findsOneWidget);
    expect(find.text('Create Order'), findsNothing);
    expect(find.text('Administrator access is restricted to the Web Dashboard.'), findsNothing);
  });
}
