import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import 'config/app_config.dart';
import 'utils/cold_start_http.dart';

const _secureTokenKey = 'access_token';
const _secureRoleKey = 'user_role';
final _secureStorage = FlutterSecureStorage();

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  // Background message handler
}

void _handleNotificationTap(RemoteMessage message) async {
  final accessToken = await _secureStorage.read(key: _secureTokenKey);
  final role = await _secureStorage.read(key: _secureRoleKey) ?? 'parent';
  if (accessToken != null && accessToken.isNotEmpty) {
    navigatorKey.currentState?.pushAndRemoveUntil(
      MaterialPageRoute(
        builder: (_) => RoleBasedHomeScreen(
          accessToken: accessToken,
          role: role,
        ),
      ),
      (route) => false,
    );
  }
}

class NotificationSync {
  static const _deviceTokenStorageKey = 'device_fcm_token';
  static bool _initialized = false;

  /// Initializes Firebase and configures runtime notification handlers.
  static Future<void> initialize() async {
    if (_initialized) return;
    try {
      await Firebase.initializeApp();
      FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);

      // Request runtime notification permissions for Android 13+
      await FirebaseMessaging.instance.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );

      // Fetch FCM token and cache locally
      // ignore: deprecated_member_use
      final token = await FirebaseMessaging.instance.getToken();
      if (token != null && token.isNotEmpty) {
        await _secureStorage.write(key: _deviceTokenStorageKey, value: token);
      }

      // Listen for token refreshes
      // ignore: deprecated_member_use
      FirebaseMessaging.instance.onTokenRefresh.listen((newToken) async {
        await _secureStorage.write(key: _deviceTokenStorageKey, value: newToken);
        final accessToken = await _secureStorage.read(key: _secureTokenKey);
        if (accessToken != null && accessToken.isNotEmpty) {
          await registerToken(accessToken);
        }
      });

      // Handle foreground notifications
      FirebaseMessaging.onMessage.listen((RemoteMessage message) {
        final notification = message.notification;
        if (notification != null) {
          final context = navigatorKey.currentContext;
          if (context != null && context.mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('${notification.title ?? "School Bus Alert"}: ${notification.body ?? ""}'),
                backgroundColor: const Color(0xFF1E3A8A),
                duration: const Duration(seconds: 6),
                action: SnackBarAction(
                  label: 'View',
                  textColor: Colors.amber,
                  onPressed: () => _handleNotificationTap(message),
                ),
              ),
            );
          }
        }
      });

      // Handle tapped notification from background
      FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
        _handleNotificationTap(message);
      });

      // Handle notification opening app from terminated state
      final initialMessage = await FirebaseMessaging.instance.getInitialMessage();
      if (initialMessage != null) {
        _handleNotificationTap(initialMessage);
      }

      _initialized = true;
    } catch (e) {
      // Gracefully continue if Firebase is not yet configured or in test environments
      debugPrint('Firebase messaging initialization skipped: $e');
    }
  }

  /// Registers device token with backend if one exists, otherwise gracefully does nothing.
  static Future<void> registerToken(String accessToken) async {
    try {
      var token = await _secureStorage.read(key: _deviceTokenStorageKey);
      if (token == null || token.isEmpty) {
        try {
          // ignore: deprecated_member_use
          token = await FirebaseMessaging.instance.getToken();
          if (token != null) {
            await _secureStorage.write(key: _deviceTokenStorageKey, value: token);
          }
        } catch (_) {}
      }
      if (token == null || token.isEmpty) return;

      await ColdStartHttpClient.post(
        AppConfig.notificationsRegisterTokenUri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer $accessToken',
        },
        body: jsonEncode({
          'token': token,
          'platform': 'android',
        }),
      );
    } catch (_) {
      // Gracefully ignore notification registration failure without crashing
    }
  }

  /// Unregisters device token from backend on sign out if one exists.
  static Future<void> unregisterToken(String? accessToken) async {
    try {
      final token = await _secureStorage.read(key: _deviceTokenStorageKey);
      if (token == null || token.isEmpty || accessToken == null || accessToken.isEmpty) return;

      await ColdStartHttpClient.post(
        AppConfig.notificationsUnregisterTokenUri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer $accessToken',
        },
        body: jsonEncode({
          'token': token,
        }),
      );
    } catch (_) {
      // Gracefully ignore notification unregistration failure
    }
  }
}

Future<void> _signOut(BuildContext context) async {
  final accessToken = await _secureStorage.read(key: _secureTokenKey);
  await NotificationSync.unregisterToken(accessToken);
  await _secureStorage.delete(key: _secureTokenKey);
  await _secureStorage.delete(key: _secureRoleKey);
  if (!context.mounted) return;
  Navigator.of(context).pushAndRemoveUntil(
    MaterialPageRoute(builder: (_) => const LoginScreen()),
    (route) => false,
  );
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await NotificationSync.initialize();
  runApp(
    ChangeNotifierProvider(
      create: (_) => DriverSharingController(),
      child: const SchoolBusTrackerApp(),
    ),
  );
}

class DriverSharingController extends ChangeNotifier {
  bool _isSharing = false;
  bool _isLoading = false;
  String? _errorMessage;
  String? _lastUpdated;
  StreamSubscription<Position>? _positionSubscription;
  String? _activeBusId;
  String? _accessToken;
  int _consecutiveFailures = 0;
  bool _isPosting = false;
  DateTime? _nextAllowedPostTime;

  bool get isSharing => _isSharing;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;
  String? get lastUpdated => _lastUpdated;
  bool get hasActiveSubscription => _positionSubscription != null;

  Future<void> startSharing({
    required String busId,
    required String accessToken,
  }) async {
    if (_positionSubscription != null) {
      return;
    }

    _isLoading = true;
    _errorMessage = null;
    _consecutiveFailures = 0;
    _nextAllowedPostTime = null;
    notifyListeners();

    try {
      final hasPermission = await _requestLocationPermission();
      if (!hasPermission) {
        _isLoading = false;
        notifyListeners();
        return;
      }

      _activeBusId = busId;
      _accessToken = accessToken;
      _positionSubscription = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 10,
        ),
      ).listen((position) async {
        if (_positionSubscription == null || !_isSharing || _isPosting) {
          return;
        }

        // Handle backoff delay if previous request failed
        if (_nextAllowedPostTime != null && DateTime.now().isBefore(_nextAllowedPostTime!)) {
          return;
        }

        _isPosting = true;
        try {
          final response = await http.post(
            AppConfig.gpsUriForBus(_activeBusId ?? busId),
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'Authorization': 'Bearer ${_accessToken ?? accessToken}',
            },
            body: jsonEncode({
              'latitude': position.latitude,
              'longitude': position.longitude,
              'speed': position.speed >= 0 ? position.speed : 0.0,
              'heading': position.heading >= 0 ? position.heading : null,
            }),
          );

          if (response.statusCode >= 200 && response.statusCode < 300) {
            final body = jsonDecode(response.body) as Map<String, dynamic>;
            final timestamp = body['timestamp']?.toString();
            _lastUpdated = timestamp != null
                ? 'Last update: $timestamp'
                : 'Location shared';
            _errorMessage = null;
            _consecutiveFailures = 0;
            _nextAllowedPostTime = null;
            notifyListeners();
            return;
          }

          final body = response.body.isNotEmpty
              ? jsonDecode(response.body)
              : <String, dynamic>{};
          _errorMessage =
              (body['detail'] ?? 'Unable to share location.').toString();
          _consecutiveFailures++;
          final backoffSec = math.min(math.pow(2, _consecutiveFailures).toInt(), 30);
          _nextAllowedPostTime = DateTime.now().add(Duration(seconds: backoffSec));
          notifyListeners();
        } catch (_) {
          _consecutiveFailures++;
          final backoffSec = math.min(math.pow(2, _consecutiveFailures).toInt(), 30);
          _errorMessage = 'Network connection issue. Retrying in ${backoffSec}s...';
          _nextAllowedPostTime = DateTime.now().add(Duration(seconds: backoffSec));
          notifyListeners();
        } finally {
          _isPosting = false;
        }
      });

      _isSharing = true;
      _isLoading = false;
      notifyListeners();
    } catch (_) {
      _errorMessage = 'Unable to fetch your current location. Please verify GPS settings.';
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> stopSharing() async {
    await _positionSubscription?.cancel();
    _positionSubscription = null;
    _isSharing = false;
    _isLoading = false;
    _lastUpdated = null;
    _errorMessage = null;
    _consecutiveFailures = 0;
    _nextAllowedPostTime = null;
    notifyListeners();
  }

  Future<bool> _requestLocationPermission() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      _errorMessage = 'Location services (GPS) are turned off. Please enable device location in settings.';
      return false;
    }

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }

    if (permission == LocationPermission.deniedForever) {
      _errorMessage = 'Location permissions are permanently denied. Please allow them from App Settings.';
      return false;
    }

    if (permission != LocationPermission.whileInUse && permission != LocationPermission.always) {
      _errorMessage = 'Location permission is required to send live GPS coordinates.';
      return false;
    }

    return true;
  }

  @override
  void dispose() {
    _positionSubscription?.cancel();
    super.dispose();
  }
}

class SchoolBusTrackerApp extends StatelessWidget {
  const SchoolBusTrackerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navigatorKey,
      title: 'School Bus Tracker',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFF59E0B),
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: const Color(0xFFF7F7F7),
      ),
      home: const AuthGate(),
    );
  }
}

class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  bool _isLoading = true;
  String? _statusMessage;

  @override
  void initState() {
    super.initState();
    _validateStoredToken();
  }

  Future<void> _validateStoredToken() async {
    final accessToken = await _secureStorage.read(key: _secureTokenKey);
    if (accessToken == null) {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
      return;
    }

    try {
      final response = await ColdStartHttpClient.get(
        AppConfig.authMeUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer $accessToken',
        },
        onStatusChange: (msg) {
          if (mounted) {
            setState(() {
              _statusMessage = msg;
            });
          }
        },
      );

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final data = response.body.isNotEmpty
            ? jsonDecode(response.body) as Map<String, dynamic>
            : <String, dynamic>{};
        final role = data['role']?.toString() ?? 'parent';
        await _secureStorage.write(key: _secureRoleKey, value: role);
        await NotificationSync.registerToken(accessToken);
        if (mounted) {
          Navigator.of(context).pushReplacement(
            MaterialPageRoute(
              builder: (_) => RoleBasedHomeScreen(
                accessToken: accessToken,
                role: role,
              ),
            ),
          );
        }
        return;
      }
    } catch (_) {
      // ignore and fall through to login
    }

    await _secureStorage.delete(key: _secureTokenKey);
    await _secureStorage.delete(key: _secureRoleKey);
    if (mounted) {
      setState(() {
        _isLoading = false;
        _statusMessage = null;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const CircularProgressIndicator(),
              if (_statusMessage != null) ...[
                const SizedBox(height: 16),
                Text(
                  _statusMessage!,
                  style: const TextStyle(color: Colors.black54, fontSize: 14),
                ),
              ],
            ],
          ),
        ),
      );
    }
    return const LoginScreen();
  }
}

class RoleBasedHomeScreen extends StatelessWidget {
  const RoleBasedHomeScreen({
    super.key,
    required this.accessToken,
    required this.role,
  });

  final String accessToken;
  final String role;

  @override
  Widget build(BuildContext context) {
    switch (role.toLowerCase()) {
      case 'admin':
        return AdminHomeScreen(accessToken: accessToken);
      case 'teacher':
        return TeacherHomeScreen(accessToken: accessToken);
      case 'driver':
        return DriverModeScreen(
          accessToken: accessToken,
          buses: const [],
        );
      case 'parent':
      default:
        return ParentHomeScreen(accessToken: accessToken);
    }
  }
}

Widget _detailRow(String label, String value) {
  return Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Row(
      children: [
        SizedBox(
          width: 110,
          child: Text(
            '$label:',
            style: const TextStyle(
              color: Colors.black54,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        Expanded(child: Text(value)),
      ],
    ),
  );
}

class ParentHomeScreen extends StatefulWidget {
  const ParentHomeScreen({
    super.key,
    required this.accessToken,
  });

  final String accessToken;

  @override
  State<ParentHomeScreen> createState() => _ParentHomeScreenState();
}

class _ParentHomeScreenState extends State<ParentHomeScreen> {
  bool _isLoading = true;
  String? _statusMessage;
  String? _errorMessage;
  Map<String, dynamic>? _selectedChild;
  Map<String, dynamic>? _bus;
  Map<String, dynamic>? _driver;

  @override
  void initState() {
    super.initState();
    _loadParentData();
  }

  Future<void> _loadParentData() async {
    setState(() {
      _isLoading = true;
      _statusMessage = null;
      _errorMessage = null;
    });

    try {
      final response = await ColdStartHttpClient.get(
        AppConfig.studentsUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
        onStatusChange: (msg) {
          if (mounted) {
            setState(() {
              _statusMessage = msg;
            });
          }
        },
      );

      if (!mounted) return;

      if (response.statusCode < 200 || response.statusCode >= 300) {
        final body = response.body.isNotEmpty
            ? jsonDecode(response.body)
            : <String, dynamic>{};
        setState(() {
          _errorMessage = (body['detail'] ?? 'Unable to load your child profile.').toString();
          _isLoading = false;
          _statusMessage = null;
        });
        return;
      }

      final payload = jsonDecode(response.body) as List<dynamic>;
      final children = payload
          .map((item) => item as Map<String, dynamic>)
          .toList(growable: false);

      final selectedChild = children.isNotEmpty ? children.first : null;
      Map<String, dynamic>? route;
      Map<String, dynamic>? bus;
      Map<String, dynamic>? driver;

      final effectiveRouteId = selectedChild?['effective_route_id']?.toString() ??
          selectedChild?['route_id']?.toString();
      final effectiveBusId = selectedChild?['effective_bus_id']?.toString();

      if (effectiveRouteId != null && effectiveRouteId.isNotEmpty) {
        final routeResponse = await ColdStartHttpClient.get(
          AppConfig.routeById(effectiveRouteId),
          headers: {
            'Accept': 'application/json',
            'Authorization': 'Bearer ${widget.accessToken}',
          },
        );

        if (routeResponse.statusCode >= 200 && routeResponse.statusCode < 300) {
          route = jsonDecode(routeResponse.body) as Map<String, dynamic>;
        }
      }

      final targetBusId = effectiveBusId ?? (route != null && route['bus_id'] != null ? route['bus_id'].toString() : null);

      if (targetBusId != null && targetBusId.isNotEmpty) {
        final busResponse = await http.get(
          Uri.parse('${AppConfig.apiBaseUrl}/api/v1/buses/$targetBusId'),
          headers: {
            'Accept': 'application/json',
            'Authorization': 'Bearer ${widget.accessToken}',
          },
        );
        if (busResponse.statusCode >= 200 && busResponse.statusCode < 300) {
          bus = jsonDecode(busResponse.body) as Map<String, dynamic>;
        }
      }

      if (selectedChild != null && selectedChild['effective_driver'] != null) {
        driver = selectedChild['effective_driver'] as Map<String, dynamic>;
      } else if (bus != null && bus['driver_id'] != null) {
        final driverResponse = await http.get(
          AppConfig.driverById(bus['driver_id'].toString()),
          headers: {
            'Accept': 'application/json',
            'Authorization': 'Bearer ${widget.accessToken}',
          },
        );
        if (driverResponse.statusCode >= 200 && driverResponse.statusCode < 300) {
          driver = jsonDecode(driverResponse.body) as Map<String, dynamic>;
        }
      }

      if (!mounted) return;

      setState(() {
        _selectedChild = selectedChild;
        _bus = bus;
        _driver = driver;
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
        _isLoading = false;
      });
    }
  }

  Future<void> _showBusMap() async {
    if (_bus == null) {
      return;
    }

    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => BusMapScreen(
          accessToken: widget.accessToken,
          busId: _bus!['id'].toString(),
          busNumber: _bus!['bus_number'].toString(),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Parent Dashboard'),
        actions: [
          IconButton(
            onPressed: () => _signOut(context),
            icon: const Icon(Icons.logout_rounded),
            tooltip: 'Sign out',
          ),
        ],
      ),
      body: SafeArea(
        child: _isLoading
            ? Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const CircularProgressIndicator(),
                    if (_statusMessage != null) ...[
                      const SizedBox(height: 16),
                      Text(
                        _statusMessage!,
                        style: const TextStyle(color: Colors.black54, fontSize: 14),
                      ),
                    ],
                  ],
                ),
              )
            : Padding(
                padding: const EdgeInsets.all(16),
                child: _errorMessage != null
                    ? _buildErrorState()
                    : _buildParentContent(),
              ),
      ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline_rounded, size: 52, color: Colors.red),
          const SizedBox(height: 16),
          Text(
            _errorMessage!,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 16),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _loadParentData,
            child: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildParentContent() {
    if (_selectedChild == null) {
      return _buildEmptyState(
        title: 'No child assigned yet',
        message: 'Your parent account does not have any assigned students yet. Please contact your administrator.',
      );
    }

    return ListView(
      padding: const EdgeInsets.all(0),
      children: [
        _buildSectionTitle('Your child'),
        Card(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${_selectedChild!['first_name']} ${_selectedChild!['last_name']}',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                _detailRow('Grade', _selectedChild!['grade']?.toString() ?? 'N/A'),
                _detailRow('Pickup', _selectedChild!['pickup_stop']?.toString() ?? 'Not set'),
                _detailRow('Dropoff', _selectedChild!['dropoff_stop']?.toString() ?? 'Not set'),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        _buildSectionTitle('Bus assignment'),
        if (_bus == null)
          _buildEmptyState(
            title: 'Bus not assigned yet',
            message: 'Your child is not assigned to a bus yet. The bus status and map will appear once the admin creates the route.',
          )
        else ...[
          Card(
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _bus!['bus_number']?.toString() ?? 'Unknown bus',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 8),
                  _detailRow('License plate', _bus!['license_plate']?.toString() ?? 'N/A'),
                  _detailRow('Status', _bus!['status']?.toString() ?? 'active'),
                  const Divider(height: 28),
                  _detailRow('Driver', _driver != null ? _driver!['license_number']?.toString() ?? 'Assigned' : 'Unassigned'),
                  _detailRow('Phone', _driver != null ? _driver!['phone']?.toString() ?? 'N/A' : 'N/A'),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _showBusMap,
                      icon: const Icon(Icons.map_outlined),
                      label: const Text('View bus location'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
        const SizedBox(height: 16),
        _buildSectionTitle('Temporary changes'),
        Card(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            leading: Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFFF59E0B).withValues(alpha: 30),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Icon(Icons.alt_route_rounded, color: Color(0xFFF59E0B)),
            ),
            title: const Text('Route & bus change requests', style: TextStyle(fontWeight: FontWeight.bold)),
            subtitle: const Text('Request a temporary route change or check review status.'),
            trailing: const Icon(Icons.arrow_forward_ios_rounded, size: 16),
            onTap: () {
              Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => ParentRouteChangeRequestsScreen(
                    accessToken: widget.accessToken,
                    childStudent: _selectedChild,
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildSectionTitle(String title) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Text(
        title,
        style: Theme.of(context).textTheme.titleLarge,
      ),
    );
  }

  Widget _buildEmptyState({required String title, required String message}) {
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(message),
            ],
          ),
        ),
      ),
    );
  }
}

class AdminHomeScreen extends StatelessWidget {
  const AdminHomeScreen({
    super.key,
    required this.accessToken,
  });

  final String accessToken;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Admin Dashboard'),
        actions: [
          IconButton(
            onPressed: () => _signOut(context),
            icon: const Icon(Icons.logout_rounded),
            tooltip: 'Sign out',
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: ListView(
            children: [
              const Text('Manage school operations', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
              const SizedBox(height: 20),
              _actionCard(
                context,
                icon: Icons.school_rounded,
                title: 'Manage students',
                description: 'Create students, assign a parent, and assign a bus route.',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => StudentListScreen(accessToken: accessToken),
                  ),
                ),
              ),
              _actionCard(
                context,
                icon: Icons.app_registration_rounded,
                title: 'Manage routes',
                description: 'Assign teachers and buses to routes.',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => RouteListScreen(accessToken: accessToken),
                  ),
                ),
              ),
              _actionCard(
                context,
                icon: Icons.drive_eta_rounded,
                title: 'Manage drivers',
                description: 'Update driver phone numbers and license information.',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => DriverListScreen(accessToken: accessToken),
                  ),
                ),
              ),
              _actionCard(
                context,
                icon: Icons.directions_bus_rounded,
                title: 'View buses',
                description: 'Review buses and get access to the bus list screen.',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => BusListScreen(accessToken: accessToken),
                  ),
                ),
              ),
              _actionCard(
                context,
                icon: Icons.alt_route_rounded,
                title: 'Route change requests',
                description: 'Review and approve temporary bus/route change requests from parents.',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => AdminRouteChangeRequestsScreen(accessToken: accessToken),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _actionCard(BuildContext context, {required IconData icon, required String title, required String description, required VoidCallback onTap}) {
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(
            children: [
              Container(
                decoration: BoxDecoration(
                  color: const Color(0xFFF59E0B).withValues(alpha: 31),
                  borderRadius: BorderRadius.circular(14),
                ),
                width: 48,
                height: 48,
                child: Icon(icon, color: const Color(0xFFF59E0B)),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    Text(description),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward_ios_rounded, size: 18),
            ],
          ),
        ),
      ),
    );
  }
}

class ParentRouteChangeRequestsScreen extends StatefulWidget {
  const ParentRouteChangeRequestsScreen({
    super.key,
    required this.accessToken,
    this.childStudent,
  });

  final String accessToken;
  final Map<String, dynamic>? childStudent;

  @override
  State<ParentRouteChangeRequestsScreen> createState() => _ParentRouteChangeRequestsScreenState();
}

class _ParentRouteChangeRequestsScreenState extends State<ParentRouteChangeRequestsScreen> {
  bool _isLoading = true;
  String? _errorMessage;
  List<Map<String, dynamic>> _requests = [];
  List<Map<String, dynamic>> _routes = [];

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final reqFuture = http.get(
        AppConfig.routeChangeRequestsUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );

      final routeFuture = http.get(
        AppConfig.routesUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );

      final results = await Future.wait([reqFuture, routeFuture]);
      final reqResp = results[0];
      final routeResp = results[1];

      if (reqResp.statusCode >= 200 && reqResp.statusCode < 300) {
        final raw = jsonDecode(reqResp.body) as List<dynamic>;
        _requests = raw.map((e) => e as Map<String, dynamic>).toList();
      }

      if (routeResp.statusCode >= 200 && routeResp.statusCode < 300) {
        final raw = jsonDecode(routeResp.body) as List<dynamic>;
        _routes = raw.map((e) => e as Map<String, dynamic>).toList();
      }

      setState(() {
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _errorMessage = 'Failed to load requests: $e';
        _isLoading = false;
      });
    }
  }

  Future<void> _openCreateDialog() async {
    if (widget.childStudent == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No student assigned to this parent.')),
      );
      return;
    }

    if (_routes.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No available routes found.')),
      );
      return;
    }

    String? selectedRouteId = _routes.first['id']?.toString();
    DateTime startDate = DateTime.now();
    DateTime endDate = DateTime.now().add(const Duration(days: 1));
    final reasonController = TextEditingController();

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (modalCtx, setModalState) {
            return Padding(
              padding: EdgeInsets.only(
                left: 20,
                right: 20,
                top: 20,
                bottom: MediaQuery.of(modalCtx).viewInsets.bottom + 20,
              ),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'Request Route Change',
                      style: Theme.of(modalCtx).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'For: ${widget.childStudent!['first_name']} ${widget.childStudent!['last_name']}',
                      style: TextStyle(color: Colors.grey.shade700, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<String>(
                      initialValue: selectedRouteId,
                      decoration: const InputDecoration(
                        labelText: 'Target Route',
                        border: OutlineInputBorder(),
                      ),
                      items: _routes.map((r) {
                        return DropdownMenuItem<String>(
                          value: r['id']?.toString(),
                          child: Text(r['name']?.toString() ?? 'Route'),
                        );
                      }).toList(),
                      onChanged: (val) {
                        setModalState(() {
                          selectedRouteId = val;
                        });
                      },
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            icon: const Icon(Icons.calendar_today_rounded, size: 16),
                            label: Text('From: ${startDate.year}-${startDate.month.toString().padLeft(2, '0')}-${startDate.day.toString().padLeft(2, '0')}'),
                            onPressed: () async {
                              final picked = await showDatePicker(
                                context: modalCtx,
                                initialDate: startDate,
                                firstDate: DateTime.now(),
                                lastDate: DateTime.now().add(const Duration(days: 90)),
                              );
                              if (picked != null) {
                                setModalState(() {
                                  startDate = picked;
                                  if (endDate.isBefore(startDate)) {
                                    endDate = startDate;
                                  }
                                });
                              }
                            },
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: OutlinedButton.icon(
                            icon: const Icon(Icons.calendar_today_rounded, size: 16),
                            label: Text('To: ${endDate.year}-${endDate.month.toString().padLeft(2, '0')}-${endDate.day.toString().padLeft(2, '0')}'),
                            onPressed: () async {
                              final picked = await showDatePicker(
                                context: modalCtx,
                                initialDate: endDate.isBefore(startDate) ? startDate : endDate,
                                firstDate: startDate,
                                lastDate: DateTime.now().add(const Duration(days: 90)),
                              );
                              if (picked != null) {
                                setModalState(() {
                                  endDate = picked;
                                });
                              }
                            },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: reasonController,
                      decoration: const InputDecoration(
                        labelText: 'Reason for temporary change',
                        border: OutlineInputBorder(),
                      ),
                      maxLines: 2,
                    ),
                    const SizedBox(height: 20),
                    FilledButton(
                      onPressed: () async {
                        final reason = reasonController.text.trim();
                        if (reason.isEmpty || selectedRouteId == null) {
                          ScaffoldMessenger.of(modalCtx).showSnackBar(
                            const SnackBar(content: Text('Please fill all fields.')),
                          );
                          return;
                        }

                        Navigator.of(modalCtx).pop();

                        final postResp = await http.post(
                          AppConfig.routeChangeRequestsUri,
                          headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                            'Authorization': 'Bearer ${widget.accessToken}',
                          },
                          body: jsonEncode({
                            'student_id': widget.childStudent!['id'].toString(),
                            'target_route_id': selectedRouteId,
                            'start_date': '${startDate.year}-${startDate.month.toString().padLeft(2, '0')}-${startDate.day.toString().padLeft(2, '0')}',
                            'end_date': '${endDate.year}-${endDate.month.toString().padLeft(2, '0')}-${endDate.day.toString().padLeft(2, '0')}',
                            'reason': reason,
                          }),
                        );

                        if (!mounted) return;
                        if (postResp.statusCode >= 200 && postResp.statusCode < 300) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('Route change request submitted successfully.')),
                          );
                          _loadData();
                        } else {
                          final err = jsonDecode(postResp.body);
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text(err['detail']?.toString() ?? 'Submission failed.')),
                          );
                        }
                      },
                      child: const Text('Submit Request'),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Future<void> _cancelRequest(String requestId) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancel Request'),
        content: const Text('Are you sure you want to cancel this pending route change request?'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('No')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Yes, Cancel')),
        ],
      ),
    );

    if (confirmed != true) return;

    final resp = await http.put(
      AppConfig.routeChangeRequestCancel(requestId),
      headers: {
        'Accept': 'application/json',
        'Authorization': 'Bearer ${widget.accessToken}',
      },
    );

    if (!mounted) return;
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Request cancelled.')),
      );
      _loadData();
    } else {
      final err = jsonDecode(resp.body);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(err['detail']?.toString() ?? 'Failed to cancel.')),
      );
    }
  }

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'approved':
        return Colors.green;
      case 'rejected':
        return Colors.red;
      case 'cancelled':
        return Colors.grey;
      case 'pending':
      default:
        return Colors.orange;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Route Change Requests'),
        actions: [
          IconButton(onPressed: _loadData, icon: const Icon(Icons.refresh_rounded)),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _openCreateDialog,
        icon: const Icon(Icons.add_rounded),
        label: const Text('New Request'),
      ),
      body: SafeArea(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _errorMessage != null
                ? Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_errorMessage!, style: const TextStyle(color: Colors.red)),
                        const SizedBox(height: 12),
                        FilledButton(onPressed: _loadData, child: const Text('Retry')),
                      ],
                    ),
                  )
                : _requests.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.alt_route_rounded, size: 56, color: Colors.grey),
                            const SizedBox(height: 16),
                            const Text(
                              'No route change requests yet.',
                              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                            ),
                            const SizedBox(height: 8),
                            const Text('Tap "+ New Request" to temporarily assign your child to another bus route.'),
                          ],
                        ),
                      )
                    : ListView.builder(
                        padding: const EdgeInsets.all(16),
                        itemCount: _requests.length,
                        itemBuilder: (ctx, idx) {
                          final req = _requests[idx];
                          final status = req['status']?.toString() ?? 'pending';
                          final isPending = status.toLowerCase() == 'pending';

                          return Card(
                            margin: const EdgeInsets.only(bottom: 12),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                            child: Padding(
                              padding: const EdgeInsets.all(16),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Expanded(
                                        child: Text(
                                          req['student_name']?.toString() ?? 'Student',
                                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                                        ),
                                      ),
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                        decoration: BoxDecoration(
                                          color: _statusColor(status).withValues(alpha: 30),
                                          borderRadius: BorderRadius.circular(12),
                                          border: Border.all(color: _statusColor(status)),
                                        ),
                                        child: Text(
                                          status.toUpperCase(),
                                          style: TextStyle(
                                            color: _statusColor(status),
                                            fontWeight: FontWeight.bold,
                                            fontSize: 11,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 8),
                                  Text(
                                    'Target Route: ${req['target_route_name'] ?? 'Route'}',
                                    style: const TextStyle(fontWeight: FontWeight.w600),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    'Dates: ${req['start_date']} to ${req['end_date']}',
                                    style: TextStyle(color: Colors.grey.shade700, fontSize: 13),
                                  ),
                                  const SizedBox(height: 6),
                                  Text('Reason: ${req['reason']}'),
                                  if (req['review_notes'] != null && req['review_notes'].toString().isNotEmpty) ...[
                                    const SizedBox(height: 6),
                                    Text('Admin note: ${req['review_notes']}', style: const TextStyle(color: Colors.blueGrey, fontStyle: FontStyle.italic)),
                                  ],
                                  if (isPending) ...[
                                    const SizedBox(height: 12),
                                    Align(
                                      alignment: Alignment.centerRight,
                                      child: OutlinedButton(
                                        onPressed: () => _cancelRequest(req['id'].toString()),
                                        child: const Text('Cancel Request'),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ),
                          );
                        },
                      ),
      ),
    );
  }
}

class AdminRouteChangeRequestsScreen extends StatefulWidget {
  const AdminRouteChangeRequestsScreen({
    super.key,
    required this.accessToken,
  });

  final String accessToken;

  @override
  State<AdminRouteChangeRequestsScreen> createState() => _AdminRouteChangeRequestsScreenState();
}

class _AdminRouteChangeRequestsScreenState extends State<AdminRouteChangeRequestsScreen> {
  bool _isLoading = true;
  String? _errorMessage;
  List<Map<String, dynamic>> _requests = [];
  String _selectedStatus = 'all';

  @override
  void initState() {
    super.initState();
    _loadRequests();
  }

  Future<void> _loadRequests() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final uri = _selectedStatus == 'all'
          ? AppConfig.routeChangeRequestsUri
          : Uri.parse('${AppConfig.routeChangeRequestsUri}?status=$_selectedStatus');

      final resp = await http.get(
        uri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final raw = jsonDecode(resp.body) as List<dynamic>;
        setState(() {
          _requests = raw.map((e) => e as Map<String, dynamic>).toList();
          _isLoading = false;
        });
      } else {
        final err = jsonDecode(resp.body);
        setState(() {
          _errorMessage = err['detail']?.toString() ?? 'Failed to load requests.';
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = 'Failed to load requests: $e';
        _isLoading = false;
      });
    }
  }

  Future<void> _approveRequest(String id) async {
    final resp = await http.put(
      AppConfig.routeChangeRequestApprove(id),
      headers: {
        'Accept': 'application/json',
        'Authorization': 'Bearer ${widget.accessToken}',
      },
    );

    if (!mounted) return;
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Request approved successfully.')),
      );
      _loadRequests();
    } else {
      final err = jsonDecode(resp.body);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(err['detail']?.toString() ?? 'Failed to approve request.')),
      );
    }
  }

  Future<void> _rejectRequest(String id) async {
    final notesController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Reject Request'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Enter rejection reason or notes for the parent:'),
            const SizedBox(height: 12),
            TextField(
              controller: notesController,
              decoration: const InputDecoration(
                labelText: 'Notes',
                border: OutlineInputBorder(),
              ),
              maxLines: 2,
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Reject'),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    final resp = await http.put(
      AppConfig.routeChangeRequestReject(id),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': 'Bearer ${widget.accessToken}',
      },
      body: jsonEncode({
        'review_notes': notesController.text.trim(),
      }),
    );

    if (!mounted) return;
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Request rejected.')),
      );
      _loadRequests();
    } else {
      final err = jsonDecode(resp.body);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(err['detail']?.toString() ?? 'Failed to reject request.')),
      );
    }
  }

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'approved':
        return Colors.green;
      case 'rejected':
        return Colors.red;
      case 'cancelled':
        return Colors.grey;
      case 'pending':
      default:
        return Colors.orange;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Review Route Changes'),
        actions: [
          IconButton(onPressed: _loadRequests, icon: const Icon(Icons.refresh_rounded)),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: ['all', 'pending', 'approved', 'rejected', 'cancelled'].map((st) {
                  final isSelected = _selectedStatus == st;
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: FilterChip(
                      label: Text(st.toUpperCase()),
                      selected: isSelected,
                      onSelected: (val) {
                        setState(() {
                          _selectedStatus = st;
                        });
                        _loadRequests();
                      },
                    ),
                  );
                }).toList(),
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _errorMessage != null
                      ? Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(_errorMessage!, style: const TextStyle(color: Colors.red)),
                              const SizedBox(height: 12),
                              FilledButton(onPressed: _loadRequests, child: const Text('Retry')),
                            ],
                          ),
                        )
                      : _requests.isEmpty
                          ? Center(
                              child: Text('No ${_selectedStatus == "all" ? "" : _selectedStatus} requests found.'),
                            )
                          : ListView.builder(
                              padding: const EdgeInsets.all(16),
                              itemCount: _requests.length,
                              itemBuilder: (ctx, idx) {
                                final req = _requests[idx];
                                final status = req['status']?.toString() ?? 'pending';
                                final isPending = status.toLowerCase() == 'pending';

                                return Card(
                                  margin: const EdgeInsets.only(bottom: 12),
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                                  child: Padding(
                                    padding: const EdgeInsets.all(16),
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Row(
                                          children: [
                                            Expanded(
                                              child: Text(
                                                req['student_name']?.toString() ?? 'Student',
                                                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                                              ),
                                            ),
                                            Container(
                                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                              decoration: BoxDecoration(
                                                color: _statusColor(status).withValues(alpha: 30),
                                                borderRadius: BorderRadius.circular(12),
                                                border: Border.all(color: _statusColor(status)),
                                              ),
                                              child: Text(
                                                status.toUpperCase(),
                                                style: TextStyle(
                                                  color: _statusColor(status),
                                                  fontWeight: FontWeight.bold,
                                                  fontSize: 11,
                                                ),
                                              ),
                                            ),
                                          ],
                                        ),
                                        const SizedBox(height: 8),
                                        Text('Target: ${req['target_route_name'] ?? 'Route'}', style: const TextStyle(fontWeight: FontWeight.w600)),
                                        const SizedBox(height: 4),
                                        Text('Dates: ${req['start_date']} to ${req['end_date']}', style: TextStyle(color: Colors.grey.shade700, fontSize: 13)),
                                        const SizedBox(height: 6),
                                        Text('Reason: ${req['reason']}'),
                                        if (isPending) ...[
                                          const SizedBox(height: 14),
                                          Row(
                                            mainAxisAlignment: MainAxisAlignment.end,
                                            children: [
                                              OutlinedButton(
                                                onPressed: () => _rejectRequest(req['id'].toString()),
                                                style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
                                                child: const Text('Reject'),
                                              ),
                                              const SizedBox(width: 8),
                                              FilledButton(
                                                onPressed: () => _approveRequest(req['id'].toString()),
                                                style: FilledButton.styleFrom(backgroundColor: Colors.green),
                                                child: const Text('Approve'),
                                              ),
                                            ],
                                          ),
                                        ],
                                      ],
                                    ),
                                  ),
                                );
                              },
                            ),
            ),
          ],
        ),
      ),
    );
  }
}

class StudentListScreen extends StatefulWidget {
  const StudentListScreen({super.key, required this.accessToken});

  final String accessToken;

  @override
  State<StudentListScreen> createState() => _StudentListScreenState();
}

class _StudentListScreenState extends State<StudentListScreen> {
  bool _isLoading = true;
  String? _errorMessage;
  List<Map<String, dynamic>> _students = const [];

  @override
  void initState() {
    super.initState();
    _loadStudents();
  }

  Future<void> _loadStudents() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final response = await http.get(
        AppConfig.studentsUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );
      if (!mounted) return;

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final body = jsonDecode(response.body) as List<dynamic>;
        setState(() {
          _students = body.map((e) => e as Map<String, dynamic>).toList();
          _isLoading = false;
        });
        return;
      }

      final body = response.body.isNotEmpty ? jsonDecode(response.body) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to load students.').toString();
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
        _isLoading = false;
      });
    }
  }

  Future<void> _editStudent(Map<String, dynamic>? student) async {
    final updated = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => StudentEditScreen(
          accessToken: widget.accessToken,
          student: student,
        ),
      ),
    );
    if (updated == true && mounted) {
      _loadStudents();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Students')),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _editStudent(null),
        tooltip: 'Add student',
        child: const Icon(Icons.add_rounded),
      ),
      body: SafeArea(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _errorMessage != null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.error_outline_rounded, size: 48),
                          const SizedBox(height: 16),
                          Text(_errorMessage!, textAlign: TextAlign.center),
                          const SizedBox(height: 16),
                          FilledButton(
                            onPressed: _loadStudents,
                            child: const Text('Retry'),
                          ),
                        ],
                      ),
                    ),
                  )
                : _students.isEmpty
                    ? Center(
                        child: Padding(
                          padding: const EdgeInsets.all(24),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: const [
                              Icon(Icons.person_off_rounded, size: 48),
                              SizedBox(height: 16),
                              Text('No students found.'),
                            ],
                          ),
                        ),
                      )
                    : ListView.separated(
                        padding: const EdgeInsets.all(16),
                        itemCount: _students.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 12),
                        itemBuilder: (context, index) {
                          final student = _students[index];
                          return Card(
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
                            child: ListTile(
                              title: Text('${student['first_name']} ${student['last_name']}'),
                              subtitle: Text('Grade ${student['grade'] ?? 'N/A'}'),
                              trailing: IconButton(
                                icon: const Icon(Icons.edit_rounded),
                                onPressed: () => _editStudent(student),
                              ),
                            ),
                          );
                        },
                      ),
      ),
    );
  }
}

class StudentEditScreen extends StatefulWidget {
  const StudentEditScreen({
    super.key,
    required this.accessToken,
    this.student,
  });

  final String accessToken;
  final Map<String, dynamic>? student;

  @override
  State<StudentEditScreen> createState() => _StudentEditScreenState();
}

class _StudentEditScreenState extends State<StudentEditScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _firstNameController;
  late final TextEditingController _lastNameController;
  late final TextEditingController _gradeController;
  late final TextEditingController _parentIdController;
  late final TextEditingController _routeIdController;
  late final TextEditingController _pickupStopController;
  late final TextEditingController _dropoffStopController;
  bool _isSaving = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _firstNameController = TextEditingController(text: widget.student?['first_name']?.toString() ?? '');
    _lastNameController = TextEditingController(text: widget.student?['last_name']?.toString() ?? '');
    _gradeController = TextEditingController(text: widget.student?['grade']?.toString() ?? '');
    _parentIdController = TextEditingController(text: widget.student?['parent_id']?.toString() ?? '');
    _routeIdController = TextEditingController(text: widget.student?['route_id']?.toString() ?? '');
    _pickupStopController = TextEditingController(text: widget.student?['pickup_stop']?.toString() ?? '');
    _dropoffStopController = TextEditingController(text: widget.student?['dropoff_stop']?.toString() ?? '');
  }

  Future<void> _saveStudent() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isSaving = true;
      _errorMessage = null;
    });

    final studentData = {
      'first_name': _firstNameController.text.trim(),
      'last_name': _lastNameController.text.trim(),
      'grade': _gradeController.text.trim(),
      'parent_id': _parentIdController.text.trim().isEmpty ? null : _parentIdController.text.trim(),
      'route_id': _routeIdController.text.trim().isEmpty ? null : _routeIdController.text.trim(),
      'pickup_stop': _pickupStopController.text.trim().isEmpty ? null : _pickupStopController.text.trim(),
      'dropoff_stop': _dropoffStopController.text.trim().isEmpty ? null : _dropoffStopController.text.trim(),
    };

    try {
      final uri = widget.student == null
          ? AppConfig.studentsUri
          : Uri.parse('${AppConfig.apiBaseUrl}/api/v1/students/${widget.student!['id']}');
      final method = widget.student == null ? 'POST' : 'PUT';
      final request = http.Request(method, uri)
        ..headers.addAll({
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        })
        ..body = jsonEncode(studentData);

      final response = await http.Client().send(request);
      final responseBody = await response.stream.bytesToString();
      if (!mounted) return;

      if (response.statusCode >= 200 && response.statusCode < 300) {
        Navigator.of(context).pop(true);
        return;
      }

      final body = responseBody.isNotEmpty ? jsonDecode(responseBody) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to save student.').toString();
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSaving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = widget.student == null ? 'Add student' : 'Edit student';
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextFormField(
                  controller: _firstNameController,
                  decoration: const InputDecoration(labelText: 'First name', border: OutlineInputBorder()),
                  validator: (value) => value == null || value.trim().isEmpty ? 'First name is required' : null,
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _lastNameController,
                  decoration: const InputDecoration(labelText: 'Last name', border: OutlineInputBorder()),
                  validator: (value) => value == null || value.trim().isEmpty ? 'Last name is required' : null,
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _gradeController,
                  decoration: const InputDecoration(labelText: 'Grade', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _parentIdController,
                  decoration: const InputDecoration(labelText: 'Parent ID', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _routeIdController,
                  decoration: const InputDecoration(labelText: 'Route/Bus ID', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _pickupStopController,
                  decoration: const InputDecoration(labelText: 'Pickup stop', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _dropoffStopController,
                  decoration: const InputDecoration(labelText: 'Dropoff stop', border: OutlineInputBorder()),
                ),
                if (_errorMessage != null) ...[
                  const SizedBox(height: 16),
                  Text(_errorMessage!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 24),
                SizedBox(
                  height: 52,
                  child: FilledButton.icon(
                    onPressed: _isSaving ? null : _saveStudent,
                    icon: _isSaving
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.save_rounded),
                    label: Text(_isSaving ? 'Saving...' : 'Save student'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    _gradeController.dispose();
    _parentIdController.dispose();
    _routeIdController.dispose();
    _pickupStopController.dispose();
    _dropoffStopController.dispose();
    super.dispose();
  }
}

class RouteListScreen extends StatefulWidget {
  const RouteListScreen({super.key, required this.accessToken});

  final String accessToken;

  @override
  State<RouteListScreen> createState() => _RouteListScreenState();
}

class _RouteListScreenState extends State<RouteListScreen> {
  bool _isLoading = true;
  String? _errorMessage;
  List<Map<String, dynamic>> _routes = const [];

  @override
  void initState() {
    super.initState();
    _loadRoutes();
  }

  Future<void> _loadRoutes() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final response = await http.get(
        AppConfig.routesUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );
      if (!mounted) return;

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final body = jsonDecode(response.body) as List<dynamic>;
        setState(() {
          _routes = body.map((e) => e as Map<String, dynamic>).toList();
          _isLoading = false;
        });
        return;
      }

      final body = response.body.isNotEmpty ? jsonDecode(response.body) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to load routes.').toString();
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
        _isLoading = false;
      });
    }
  }

  Future<void> _editRoute(Map<String, dynamic> route) async {
    final updated = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => RouteEditScreen(accessToken: widget.accessToken, route: route),
      ),
    );
    if (updated == true && mounted) {
      _loadRoutes();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Routes')),
      body: SafeArea(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _errorMessage != null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.error_outline_rounded, size: 48),
                          const SizedBox(height: 16),
                          Text(_errorMessage!, textAlign: TextAlign.center),
                          const SizedBox(height: 16),
                          FilledButton(
                            onPressed: _loadRoutes,
                            child: const Text('Retry'),
                          ),
                        ],
                      ),
                    ),
                  )
                : _routes.isEmpty
                    ? const Center(child: Text('No routes available.'))
                    : ListView.separated(
                        padding: const EdgeInsets.all(16),
                        itemCount: _routes.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 12),
                        itemBuilder: (context, index) {
                          final route = _routes[index];
                          return Card(
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
                            child: ListTile(
                              title: Text(route['name']?.toString() ?? 'Route'),
                              subtitle: Text('Bus: ${route['bus_id'] ?? 'Unassigned'}\nTeacher: ${route['teacher_id'] ?? 'Unassigned'}'),
                              isThreeLine: true,
                              trailing: IconButton(
                                icon: const Icon(Icons.edit_rounded),
                                onPressed: () => _editRoute(route),
                              ),
                            ),
                          );
                        },
                      ),
      ),
    );
  }
}

class RouteEditScreen extends StatefulWidget {
  const RouteEditScreen({
    super.key,
    required this.accessToken,
    required this.route,
  });

  final String accessToken;
  final Map<String, dynamic> route;

  @override
  State<RouteEditScreen> createState() => _RouteEditScreenState();
}

class _RouteEditScreenState extends State<RouteEditScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _busIdController;
  late final TextEditingController _teacherIdController;
  late final TextEditingController _driverIdController;
  bool _isSaving = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _busIdController = TextEditingController(text: widget.route['bus_id']?.toString() ?? '');
    _teacherIdController = TextEditingController(text: widget.route['teacher_id']?.toString() ?? '');
    _driverIdController = TextEditingController(text: widget.route['driver_id']?.toString() ?? '');
  }

  Future<void> _saveRoute() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _isSaving = true;
      _errorMessage = null;
    });
    final data = {
      'bus_id': _busIdController.text.trim().isEmpty ? null : _busIdController.text.trim(),
      'teacher_id': _teacherIdController.text.trim().isEmpty ? null : _teacherIdController.text.trim(),
      'driver_id': _driverIdController.text.trim().isEmpty ? null : _driverIdController.text.trim(),
    };
    try {
      final response = await http.put(
        AppConfig.routeById(widget.route['id'].toString()),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
        body: jsonEncode(data),
      );
      if (!mounted) return;
      if (response.statusCode >= 200 && response.statusCode < 300) {
        Navigator.of(context).pop(true);
        return;
      }
      final body = response.body.isNotEmpty ? jsonDecode(response.body) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to save route.').toString();
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSaving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Assign route')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextFormField(
                  controller: _busIdController,
                  decoration: const InputDecoration(labelText: 'Bus ID', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _teacherIdController,
                  decoration: const InputDecoration(labelText: 'Teacher ID', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _driverIdController,
                  decoration: const InputDecoration(labelText: 'Driver ID', border: OutlineInputBorder()),
                ),
                if (_errorMessage != null) ...[
                  const SizedBox(height: 16),
                  Text(_errorMessage!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 24),
                SizedBox(
                  height: 52,
                  child: FilledButton.icon(
                    onPressed: _isSaving ? null : _saveRoute,
                    icon: _isSaving
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.save_rounded),
                    label: Text(_isSaving ? 'Saving...' : 'Save assignment'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _busIdController.dispose();
    _teacherIdController.dispose();
    _driverIdController.dispose();
    super.dispose();
  }
}

class DriverListScreen extends StatefulWidget {
  const DriverListScreen({super.key, required this.accessToken});

  final String accessToken;

  @override
  State<DriverListScreen> createState() => _DriverListScreenState();
}

class _DriverListScreenState extends State<DriverListScreen> {
  bool _isLoading = true;
  String? _errorMessage;
  List<Map<String, dynamic>> _drivers = const [];

  @override
  void initState() {
    super.initState();
    _loadDrivers();
  }

  Future<void> _loadDrivers() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });
    try {
      final response = await http.get(
        AppConfig.driversUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );
      if (!mounted) return;
      if (response.statusCode >= 200 && response.statusCode < 300) {
        final body = jsonDecode(response.body) as List<dynamic>;
        setState(() {
          _drivers = body.map((e) => e as Map<String, dynamic>).toList();
          _isLoading = false;
        });
        return;
      }
      final body = response.body.isNotEmpty ? jsonDecode(response.body) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to load drivers.').toString();
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
        _isLoading = false;
      });
    }
  }

  Future<void> _editDriver(Map<String, dynamic> driver) async {
    final updated = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => DriverEditScreen(accessToken: widget.accessToken, driver: driver),
      ),
    );
    if (updated == true && mounted) {
      _loadDrivers();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Drivers')),
      body: SafeArea(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _errorMessage != null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.error_outline_rounded, size: 48),
                          const SizedBox(height: 16),
                          Text(_errorMessage!, textAlign: TextAlign.center),
                          const SizedBox(height: 16),
                          FilledButton(
                            onPressed: _loadDrivers,
                            child: const Text('Retry'),
                          ),
                        ],
                      ),
                    ),
                  )
                : _drivers.isEmpty
                    ? const Center(child: Text('No drivers found.'))
                    : ListView.separated(
                        padding: const EdgeInsets.all(16),
                        itemCount: _drivers.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 12),
                        itemBuilder: (context, index) {
                          final driver = _drivers[index];
                          return Card(
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
                            child: ListTile(
                              title: Text(driver['license_number']?.toString() ?? 'Driver'),
                              subtitle: Text('Phone: ${driver['phone'] ?? 'N/A'}'),
                              trailing: IconButton(
                                icon: const Icon(Icons.edit_rounded),
                                onPressed: () => _editDriver(driver),
                              ),
                            ),
                          );
                        },
                      ),
      ),
    );
  }
}

class DriverEditScreen extends StatefulWidget {
  const DriverEditScreen({
    super.key,
    required this.accessToken,
    required this.driver,
  });

  final String accessToken;
  final Map<String, dynamic> driver;

  @override
  State<DriverEditScreen> createState() => _DriverEditScreenState();
}

class _DriverEditScreenState extends State<DriverEditScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _licenseController;
  late final TextEditingController _phoneController;
  bool _isSaving = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _licenseController = TextEditingController(text: widget.driver['license_number']?.toString() ?? '');
    _phoneController = TextEditingController(text: widget.driver['phone']?.toString() ?? '');
  }

  Future<void> _saveDriver() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _isSaving = true;
      _errorMessage = null;
    });
    try {
      final response = await http.put(
        AppConfig.driverById(widget.driver['id'].toString()),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
        body: jsonEncode({
          'license_number': _licenseController.text.trim(),
          'phone': _phoneController.text.trim(),
        }),
      );
      if (!mounted) return;
      if (response.statusCode >= 200 && response.statusCode < 300) {
        Navigator.of(context).pop(true);
        return;
      }
      final body = response.body.isNotEmpty ? jsonDecode(response.body) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to save driver.').toString();
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSaving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Edit driver')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextFormField(
                  controller: _licenseController,
                  decoration: const InputDecoration(labelText: 'License number', border: OutlineInputBorder()),
                  validator: (value) => value == null || value.trim().isEmpty ? 'License number is required' : null,
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _phoneController,
                  decoration: const InputDecoration(labelText: 'Phone', border: OutlineInputBorder()),
                  validator: (value) => value == null || value.trim().isEmpty ? 'Phone is required' : null,
                ),
                if (_errorMessage != null) ...[
                  const SizedBox(height: 16),
                  Text(_errorMessage!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 24),
                SizedBox(
                  height: 52,
                  child: FilledButton.icon(
                    onPressed: _isSaving ? null : _saveDriver,
                    icon: _isSaving
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.save_rounded),
                    label: Text(_isSaving ? 'Saving...' : 'Save driver'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _licenseController.dispose();
    _phoneController.dispose();
    super.dispose();
  }
}

class TeacherHomeScreen extends StatefulWidget {
  const TeacherHomeScreen({super.key, required this.accessToken});

  final String accessToken;

  @override
  State<TeacherHomeScreen> createState() => _TeacherHomeScreenState();
}

class _TeacherHomeScreenState extends State<TeacherHomeScreen> {
  bool _isLoading = true;
  String? _errorMessage;
  Map<String, dynamic>? _selectedRoute;
  Map<String, dynamic>? _bus;
  List<Map<String, dynamic>> _students = const [];

  @override
  void initState() {
    super.initState();
    _loadTeacherData();
  }

  Future<void> _loadTeacherData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });
    try {
      final response = await http.get(
        AppConfig.routesUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );
      if (!mounted) return;
      if (response.statusCode >= 200 && response.statusCode < 300) {
        final body = jsonDecode(response.body) as List<dynamic>;
        final routes = body.map((e) => e as Map<String, dynamic>).toList();
        final selectedRoute = routes.isNotEmpty ? routes.first : null;
        Map<String, dynamic>? bus;
        List<Map<String, dynamic>> students = const [];
        if (selectedRoute != null && selectedRoute['bus_id'] != null) {
          final busResponse = await http.get(
            Uri.parse('${AppConfig.apiBaseUrl}/api/v1/buses/${selectedRoute['bus_id']}'),
            headers: {
              'Accept': 'application/json',
              'Authorization': 'Bearer ${widget.accessToken}',
            },
          );
          if (busResponse.statusCode >= 200 && busResponse.statusCode < 300) {
            bus = jsonDecode(busResponse.body) as Map<String, dynamic>;
          }
        }
        if (selectedRoute != null) {
          final studentsResponse = await http.get(
            Uri.parse('${AppConfig.apiBaseUrl}/api/v1/students?route_id=${Uri.encodeComponent(selectedRoute['id'].toString())}'),
            headers: {
              'Accept': 'application/json',
              'Authorization': 'Bearer ${widget.accessToken}',
            },
          );
          if (studentsResponse.statusCode >= 200 && studentsResponse.statusCode < 300) {
            final studentsBody = jsonDecode(studentsResponse.body) as List<dynamic>;
            students = studentsBody.map((e) => e as Map<String, dynamic>).toList();
          }
        }
        if (!mounted) return;
        setState(() {
          _selectedRoute = selectedRoute;
          _bus = bus;
          _students = students;
          _isLoading = false;
        });
        return;
      }
      final body = response.body.isNotEmpty ? jsonDecode(response.body) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to load your assigned route.').toString();
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
        _isLoading = false;
      });
    }
  }

  Future<void> _showAttendance() async {
    if (_selectedRoute == null) {
      return;
    }
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => TeacherAttendanceScreen(
          accessToken: widget.accessToken,
          route: _selectedRoute!,
          bus: _bus,
          students: _students,
        ),
      ),
    );
    if (mounted) {
      _loadTeacherData();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Teacher Dashboard'),
        actions: [
          IconButton(
            onPressed: () => _signOut(context),
            icon: const Icon(Icons.logout_rounded),
            tooltip: 'Sign out',
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: _isLoading
              ? const Center(child: CircularProgressIndicator())
              : _errorMessage != null
                  ? _buildErrorState()
                  : _buildTeacherContent(),
        ),
      ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline_rounded, size: 52, color: Colors.red),
          const SizedBox(height: 16),
          Text(_errorMessage!, textAlign: TextAlign.center),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _loadTeacherData,
            child: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildTeacherContent() {
    if (_selectedRoute == null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: const [
            Icon(Icons.route_outlined, size: 52),
            SizedBox(height: 16),
            Text('No assigned route yet.'),
            SizedBox(height: 8),
            Text('Your administrator must assign you to a route before attendance can be marked.'),
          ],
        ),
      );
    }

    return ListView(
      children: [
        Text(_selectedRoute!['name']?.toString() ?? 'Assigned route', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 12),
        Card(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _detailRow('Route start', _selectedRoute!['start_location']?.toString() ?? 'N/A'),
                _detailRow('Route end', _selectedRoute!['end_location']?.toString() ?? 'N/A'),
                _detailRow('Route status', _selectedRoute!['status']?.toString() ?? 'N/A'),
                _detailRow('Bus', _bus != null ? _bus!['bus_number']?.toString() ?? 'Assigned' : 'Unassigned'),
                _detailRow('Bus status', _bus != null ? _bus!['status']?.toString() ?? 'N/A' : 'N/A'),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: _showAttendance,
                    icon: const Icon(Icons.checklist_rtl_rounded),
                    label: const Text('Mark attendance'),
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        const Text('Students on this route', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        ..._students.map((student) => Card(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
              child: ListTile(
                title: Text('${student['first_name']} ${student['last_name']}'),
                subtitle: Text('Grade ${student['grade'] ?? 'N/A'}'),
              ),
            )),
      ],
    );
  }
}

class TeacherAttendanceScreen extends StatefulWidget {
  const TeacherAttendanceScreen({
    super.key,
    required this.accessToken,
    required this.route,
    required this.bus,
    required this.students,
  });

  final String accessToken;
  final Map<String, dynamic> route;
  final Map<String, dynamic>? bus;
  final List<Map<String, dynamic>> students;

  @override
  State<TeacherAttendanceScreen> createState() => _TeacherAttendanceScreenState();
}

class _TeacherAttendanceScreenState extends State<TeacherAttendanceScreen> {
  late DateTime _selectedDate;
  String _selectedActionType = 'pickup';
  bool _isLoading = false;
  bool _isSubmitting = false;
  String? _errorMessage;
  String? _infoMessage;
  List<Map<String, dynamic>> _roster = [];

  @override
  void initState() {
    super.initState();
    _selectedDate = DateTime.now();
    _loadRoster();
  }

  String _formatDate(DateTime dt) =>
      '${dt.year.toString().padLeft(4, '0')}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';

  Future<void> _loadRoster() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _infoMessage = null;
    });

    final dateStr = _formatDate(_selectedDate);
    final routeId = widget.route['id']?.toString();
    try {
      final uri = Uri.parse(
        '${AppConfig.apiBaseUrl}/api/v1/attendance/roster'
        '?date=$dateStr&action_type=$_selectedActionType${routeId != null ? '&route_id=${Uri.encodeComponent(routeId)}' : ''}',
      );
      final response = await http.get(
        uri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );

      if (!mounted) return;
      if (response.statusCode >= 200 && response.statusCode < 300) {
        final body = jsonDecode(response.body) as List<dynamic>;
        setState(() {
          _roster = body.map((e) => Map<String, dynamic>.from(e as Map)).toList();
          _isLoading = false;
        });
        return;
      }

      final body = response.body.isNotEmpty ? jsonDecode(response.body) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to fetch attendance roster.').toString();
        _roster = widget.students.map((s) => {
          'student_id': s['id'],
          'first_name': s['first_name'] ?? '',
          'last_name': s['last_name'] ?? '',
          'grade': s['grade'],
          'status': null,
        }).toList();
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please check your connection.';
        _roster = widget.students.map((s) => {
          'student_id': s['id'],
          'first_name': s['first_name'] ?? '',
          'last_name': s['last_name'] ?? '',
          'grade': s['grade'],
          'status': null,
        }).toList();
        _isLoading = false;
      });
    }
  }

  Future<void> _selectDate() async {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final minDate = today.subtract(const Duration(days: 7));
    final initial = _selectedDate.isBefore(minDate)
        ? minDate
        : (_selectedDate.isAfter(today) ? today : _selectedDate);
    final picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: minDate,
      lastDate: today,
    );
    if (picked != null && picked != _selectedDate) {
      setState(() {
        _selectedDate = picked;
      });
      _loadRoster();
    }
  }

  Future<void> _markStudentAttendance(Map<String, dynamic> student, String status) async {
    final studentId = student['student_id'] ?? student['id'];
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _infoMessage = null;
    });

    try {
      final response = await http.post(
        AppConfig.attendanceUri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
        body: jsonEncode({
          'student_id': studentId,
          'bus_id': widget.bus?['id'],
          'route_id': widget.route['id'],
          'attendance_date': _formatDate(_selectedDate),
          'status': status,
          'action_type': _selectedActionType,
        }),
      );

      if (!mounted) return;
      if (response.statusCode >= 200 && response.statusCode < 300) {
        final resData = jsonDecode(response.body) as Map<String, dynamic>;
        setState(() {
          final idx = _roster.indexWhere((s) => (s['student_id'] ?? s['id']) == studentId);
          if (idx != -1) {
            _roster[idx]['status'] = resData['status'];
            _roster[idx]['attendance_id'] = resData['id'];
          }
          _infoMessage = 'Marked ${student['first_name']} ${student['last_name']} as ${resData['status']}.';
        });
        return;
      }

      final body = response.body.isNotEmpty ? jsonDecode(response.body) : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to mark attendance.').toString();
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  Future<void> _markAllPresent() async {
    if (_roster.isEmpty) return;
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _infoMessage = null;
    });

    int markedCount = 0;
    try {
      for (final student in _roster) {
        final studentId = student['student_id'] ?? student['id'];
        final response = await http.post(
          AppConfig.attendanceUri,
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': 'Bearer ${widget.accessToken}',
          },
          body: jsonEncode({
            'student_id': studentId,
            'bus_id': widget.bus?['id'],
            'route_id': widget.route['id'],
            'attendance_date': _formatDate(_selectedDate),
            'status': 'present',
            'action_type': _selectedActionType,
          }),
        );
        if (response.statusCode >= 200 && response.statusCode < 300) {
          final resData = jsonDecode(response.body) as Map<String, dynamic>;
          student['status'] = resData['status'];
          student['attendance_id'] = resData['id'];
          markedCount++;
        }
      }
      if (!mounted) return;
      setState(() {
        _infoMessage = 'Marked $markedCount student(s) as present.';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Interrupted while marking attendance. Please check student statuses.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final presentCount = _roster.where((s) => s['status'] == 'present').length;
    final absentCount = _roster.where((s) => s['status'] == 'absent').length;
    final pendingCount = _roster.length - presentCount - absentCount;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Attendance'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh roster',
            onPressed: _isLoading ? null : _loadRoster,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (_isSubmitting) const LinearProgressIndicator(),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Card(
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.directions_bus_rounded, color: Colors.blue),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  widget.bus != null
                                      ? 'Bus: ${widget.bus!['bus_number']} (${widget.bus!['license_plate'] ?? ''})'
                                      : 'Route: ${widget.route['name'] ?? 'Assigned Route'}',
                                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                                ),
                              ),
                            ],
                          ),
                          const Divider(height: 20),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Row(
                                children: [
                                  const Icon(Icons.calendar_today_rounded, size: 18),
                                  const SizedBox(width: 8),
                                  Text(
                                    'Date: ${_formatDate(_selectedDate)}',
                                    style: const TextStyle(fontWeight: FontWeight.w600),
                                  ),
                                ],
                              ),
                              OutlinedButton.icon(
                                onPressed: _isSubmitting ? null : _selectDate,
                                icon: const Icon(Icons.edit_calendar_rounded, size: 16),
                                label: const Text('Change'),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          SegmentedButton<String>(
                            segments: const [
                              ButtonSegment(
                                value: 'pickup',
                                label: Text('Morning Pickup'),
                                icon: Icon(Icons.wb_sunny_outlined),
                              ),
                              ButtonSegment(
                                value: 'dropoff',
                                label: Text('Afternoon Dropoff'),
                                icon: Icon(Icons.nights_stay_outlined),
                              ),
                            ],
                            selected: {_selectedActionType},
                            onSelectionChanged: (Set<String> newSelection) {
                              setState(() {
                                _selectedActionType = newSelection.first;
                              });
                              _loadRoster();
                            },
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: Wrap(
                          spacing: 6,
                          runSpacing: 4,
                          children: [
                            Chip(
                              label: Text('Present: $presentCount', style: const TextStyle(fontSize: 12)),
                              backgroundColor: Colors.green.withValues(alpha: 0.15),
                              side: BorderSide.none,
                            ),
                            Chip(
                              label: Text('Absent: $absentCount', style: const TextStyle(fontSize: 12)),
                              backgroundColor: Colors.red.withValues(alpha: 0.15),
                              side: BorderSide.none,
                            ),
                            Chip(
                              label: Text('Pending: $pendingCount', style: const TextStyle(fontSize: 12)),
                              backgroundColor: Colors.grey.withValues(alpha: 0.15),
                              side: BorderSide.none,
                            ),
                          ],
                        ),
                      ),
                      FilledButton.tonalIcon(
                        onPressed: _isSubmitting || _roster.isEmpty ? null : _markAllPresent,
                        icon: const Icon(Icons.done_all_rounded, size: 18),
                        label: const Text('Mark all present'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (_infoMessage != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.green.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.green.withValues(alpha: 0.3)),
                      ),
                      child: Text(_infoMessage!, style: const TextStyle(color: Colors.green, fontWeight: FontWeight.w500)),
                    ),
                    const SizedBox(height: 8),
                  ],
                  if (_errorMessage != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.red.withValues(alpha: 0.3)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.error_outline_rounded, color: Colors.red, size: 20),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(_errorMessage!, style: const TextStyle(color: Colors.red)),
                          ),
                          TextButton(onPressed: _loadRoster, child: const Text('Retry')),
                        ],
                      ),
                    ),
                    const SizedBox(height: 8),
                  ],
                  if (_isLoading)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 40),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (_roster.isEmpty)
                    Card(
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                      child: const Padding(
                        padding: EdgeInsets.symmetric(vertical: 32, horizontal: 16),
                        child: Center(
                          child: Column(
                            children: [
                              Icon(Icons.people_outline_rounded, size: 48, color: Colors.grey),
                              SizedBox(height: 12),
                              Text(
                                'No students are assigned to this route yet.',
                                style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500),
                              ),
                            ],
                          ),
                        ),
                      ),
                    )
                  else
                    ..._roster.map((student) {
                      final status = student['status'];
                      final isPresent = status == 'present';
                      final isAbsent = status == 'absent';

                      return Card(
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                        margin: const EdgeInsets.only(bottom: 12),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  CircleAvatar(
                                    backgroundColor: isPresent
                                        ? Colors.green.withValues(alpha: 0.2)
                                        : isAbsent
                                            ? Colors.red.withValues(alpha: 0.2)
                                            : Colors.grey.withValues(alpha: 0.2),
                                    child: Text(
                                      '${student['first_name']?[0] ?? ''}${student['last_name']?[0] ?? ''}'.toUpperCase(),
                                      style: TextStyle(
                                        color: isPresent
                                            ? Colors.green.shade800
                                            : isAbsent
                                                ? Colors.red.shade800
                                                : Colors.grey.shade800,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          '${student['first_name']} ${student['last_name']}',
                                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                                        ),
                                        const SizedBox(height: 4),
                                        Text('Grade: ${student['grade'] ?? 'N/A'}'),
                                        if (student['pickup_stop'] != null || student['dropoff_stop'] != null)
                                          Text(
                                            _selectedActionType == 'pickup'
                                                ? 'Stop: ${student['pickup_stop'] ?? 'Default'}'
                                                : 'Stop: ${student['dropoff_stop'] ?? 'Default'}',
                                            style: const TextStyle(fontSize: 12, color: Colors.grey),
                                          ),
                                      ],
                                    ),
                                  ),
                                  if (isPresent)
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                      decoration: BoxDecoration(
                                        color: Colors.green.withValues(alpha: 0.15),
                                        borderRadius: BorderRadius.circular(12),
                                      ),
                                      child: const Row(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          Icon(Icons.check_circle_rounded, color: Colors.green, size: 14),
                                          SizedBox(width: 4),
                                          Text('Present', style: TextStyle(color: Colors.green, fontWeight: FontWeight.bold, fontSize: 12)),
                                        ],
                                      ),
                                    )
                                  else if (isAbsent)
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                      decoration: BoxDecoration(
                                        color: Colors.red.withValues(alpha: 0.15),
                                        borderRadius: BorderRadius.circular(12),
                                      ),
                                      child: const Row(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          Icon(Icons.cancel_rounded, color: Colors.red, size: 14),
                                          SizedBox(width: 4),
                                          Text('Absent', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold, fontSize: 12)),
                                        ],
                                      ),
                                    )
                                  else
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                      decoration: BoxDecoration(
                                        color: Colors.orange.withValues(alpha: 0.15),
                                        borderRadius: BorderRadius.circular(12),
                                      ),
                                      child: const Row(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          Icon(Icons.pending_rounded, color: Colors.orange, size: 14),
                                          SizedBox(width: 4),
                                          Text('Pending', style: TextStyle(color: Colors.orange, fontWeight: FontWeight.bold, fontSize: 12)),
                                        ],
                                      ),
                                    ),
                                ],
                              ),
                              const SizedBox(height: 12),
                              Row(
                                children: [
                                  Expanded(
                                    child: isPresent
                                        ? FilledButton.icon(
                                            style: FilledButton.styleFrom(backgroundColor: Colors.green.shade700),
                                            onPressed: _isSubmitting ? null : () => _markStudentAttendance(student, 'present'),
                                            icon: const Icon(Icons.check_rounded, size: 18),
                                            label: const Text('Present'),
                                          )
                                        : OutlinedButton.icon(
                                            onPressed: _isSubmitting ? null : () => _markStudentAttendance(student, 'present'),
                                            icon: const Icon(Icons.check_rounded, size: 18),
                                            label: const Text('Present'),
                                          ),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: isAbsent
                                        ? FilledButton.icon(
                                            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
                                            onPressed: _isSubmitting ? null : () => _markStudentAttendance(student, 'absent'),
                                            icon: const Icon(Icons.close_rounded, size: 18),
                                            label: const Text('Absent'),
                                          )
                                        : OutlinedButton.icon(
                                            onPressed: _isSubmitting ? null : () => _markStudentAttendance(student, 'absent'),
                                            icon: const Icon(Icons.close_rounded, size: 18),
                                            label: const Text('Absent'),
                                          ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      );
                    }),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}


class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _isLoading = false;
  bool _obscurePassword = true;
  String? _errorMessage;
  String? _statusMessage;

  String? _validateEmail(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Email is required';
    }

    final email = value.trim();
    final emailRegex = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');
    if (!emailRegex.hasMatch(email)) {
      return 'Enter a valid email address';
    }

    return null;
  }

  String? _validatePassword(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Password is required';
    }

    if (value.length < 6) {
      return 'Password must be at least 6 characters';
    }

    return null;
  }

  Future<void> _submitLogin() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isLoading = true;
      _statusMessage = null;
      _errorMessage = null;
    });

    try {
      final response = await ColdStartHttpClient.post(
        AppConfig.authLoginUri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: jsonEncode({
          'email': _emailController.text.trim(),
          'password': _passwordController.text,
        }),
        onStatusChange: (msg) {
          if (mounted) {
            setState(() {
              _statusMessage = msg;
            });
          }
        },
      );

      if (!mounted) {
        return;
      }

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final data = response.body.isNotEmpty
            ? jsonDecode(response.body)
            : <String, dynamic>{};
        final accessToken = data['access_token'] as String?;
        if (accessToken == null || accessToken.isEmpty) {
          setState(() {
            _errorMessage = 'Login succeeded but no token was returned.';
          });
          return;
        }

        final role = data['user']?['role']?.toString() ?? 'parent';
        await _secureStorage.write(key: _secureTokenKey, value: accessToken);
        await _secureStorage.write(key: _secureRoleKey, value: role);
        await NotificationSync.registerToken(accessToken);

        if (!mounted) {
          return;
        }

        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => RoleBasedHomeScreen(
              accessToken: accessToken,
              role: role,
            ),
          ),
        );
        return;
      }

      final data = response.body.isNotEmpty
          ? jsonDecode(response.body)
          : <String, dynamic>{};
      final message =
          data['detail'] ??
          data['message'] ??
          'Login failed. Please try again.';
      setState(() {
        _errorMessage = message;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _showForgotPasswordDialog() async {
    final emailController = TextEditingController(text: _emailController.text.trim());
    bool isSending = false;
    String? dialogMessage;
    bool isSuccess = false;

    await showDialog(
      context: context,
      builder: (dialogCtx) => StatefulBuilder(
        builder: (context, setDialogState) {
          return AlertDialog(
            title: const Text('Forgot Password'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Enter your email address to receive a secure password recovery link.',
                  style: TextStyle(fontSize: 14),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: emailController,
                  keyboardType: TextInputType.emailAddress,
                  decoration: const InputDecoration(
                    labelText: 'Email',
                    prefixIcon: Icon(Icons.email_outlined),
                    border: OutlineInputBorder(),
                  ),
                ),
                if (dialogMessage != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    dialogMessage!,
                    style: TextStyle(
                      color: isSuccess ? Colors.green.shade700 : Colors.red.shade700,
                      fontSize: 13,
                    ),
                  ),
                ],
              ],
            ),
            actions: [
              TextButton(
                onPressed: isSending ? null : () => Navigator.of(dialogCtx).pop(),
                child: Text(isSuccess ? 'Close' : 'Cancel'),
              ),
              if (!isSuccess)
                FilledButton(
                  onPressed: isSending
                      ? null
                      : () async {
                          final email = emailController.text.trim();
                          if (email.isEmpty) return;
                          setDialogState(() {
                            isSending = true;
                            dialogMessage = null;
                          });
                          try {
                            final res = await http.post(
                              AppConfig.authForgotPasswordUri,
                              headers: {
                                'Content-Type': 'application/json',
                                'Accept': 'application/json',
                              },
                              body: jsonEncode({'email': email}),
                            );
                            if (res.statusCode >= 200 && res.statusCode < 300) {
                              setDialogState(() {
                                isSuccess = true;
                                isSending = false;
                                dialogMessage =
                                    'If an account with that email exists, a password reset link has been sent.';
                              });
                            } else {
                              final body = res.body.isNotEmpty
                                  ? jsonDecode(res.body)
                                  : <String, dynamic>{};
                              setDialogState(() {
                                isSending = false;
                                dialogMessage =
                                    (body['detail'] ?? 'Unable to send reset request.').toString();
                              });
                            }
                          } catch (_) {
                            setDialogState(() {
                              isSending = false;
                              dialogMessage =
                                  'Unable to connect to the server. Please try again.';
                            });
                          }
                        },
                  child: isSending
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Send Link'),
                ),
            ],
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Card(
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(28),
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(28),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.fromLTRB(24, 32, 24, 28),
                        decoration: const BoxDecoration(
                          gradient: LinearGradient(
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                            colors: [Color(0xFFF59E0B), Color(0xFFFBBF24)],
                          ),
                        ),
                        child: Column(
                          children: [
                            Container(
                              width: 76,
                              height: 76,
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: 46),
                                borderRadius: BorderRadius.circular(22),
                              ),
                              child: const Icon(
                                Icons.directions_bus_rounded,
                                size: 40,
                                color: Colors.white,
                              ),
                            ),
                            const SizedBox(height: 18),
                            const Text(
                              'School Bus Tracker',
                              style: TextStyle(
                                fontSize: 28,
                                fontWeight: FontWeight.w700,
                                color: Colors.white,
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              'Secure transportation access',
                              style: TextStyle(
                                fontSize: 14,
                                color: Colors.white.withValues(alpha: 230),
                              ),
                            ),
                          ],
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.all(24),
                        child: Form(
                          key: _formKey,
                          child: AutofillGroup(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                const SizedBox(height: 8),
                                TextFormField(
                                  controller: _emailController,
                                  keyboardType: TextInputType.emailAddress,
                                  textInputAction: TextInputAction.next,
                                  autofillHints: const [AutofillHints.username],
                                  decoration: InputDecoration(
                                    labelText: 'Email',
                                    hintText: 'name@example.com',
                                    prefixIcon: const Icon(
                                      Icons.email_outlined,
                                    ),
                                    border: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(14),
                                    ),
                                  ),
                                  validator: _validateEmail,
                                ),
                                const SizedBox(height: 18),
                                TextFormField(
                                  controller: _passwordController,
                                  obscureText: _obscurePassword,
                                  textInputAction: TextInputAction.done,
                                  autofillHints: const [AutofillHints.password],
                                  decoration: InputDecoration(
                                    labelText: 'Password',
                                    prefixIcon: const Icon(
                                      Icons.lock_outline_rounded,
                                    ),
                                    suffixIcon: IconButton(
                                      onPressed: () {
                                        setState(() {
                                          _obscurePassword = !_obscurePassword;
                                        });
                                      },
                                      icon: Icon(
                                        _obscurePassword
                                            ? Icons.visibility_outlined
                                            : Icons.visibility_off_outlined,
                                      ),
                                      tooltip: _obscurePassword
                                          ? 'Show password'
                                          : 'Hide password',
                                    ),
                                    border: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(14),
                                    ),
                                  ),
                                  validator: _validatePassword,
                                  onFieldSubmitted: (_) => _submitLogin(),
                                ),
                                Align(
                                  alignment: Alignment.centerRight,
                                  child: TextButton(
                                    onPressed: _isLoading ? null : _showForgotPasswordDialog,
                                    child: const Text('Forgot password?'),
                                  ),
                                ),
                                const SizedBox(height: 8),
                                if (_statusMessage != null)
                                  Container(
                                    padding: const EdgeInsets.all(12),
                                    margin: const EdgeInsets.only(bottom: 12),
                                    decoration: BoxDecoration(
                                      color: Colors.amber.shade50,
                                      borderRadius: BorderRadius.circular(12),
                                      border: Border.all(
                                        color: Colors.amber.shade300,
                                      ),
                                    ),
                                    child: Row(
                                      children: [
                                        SizedBox(
                                          width: 16,
                                          height: 16,
                                          child: CircularProgressIndicator(
                                            strokeWidth: 2,
                                            color: Colors.amber.shade800,
                                          ),
                                        ),
                                        const SizedBox(width: 10),
                                        Expanded(
                                          child: Text(
                                            _statusMessage!,
                                            style: TextStyle(
                                              color: Colors.amber.shade900,
                                              fontSize: 13,
                                              fontWeight: FontWeight.w500,
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                if (_errorMessage != null)
                                  Container(
                                    padding: const EdgeInsets.all(12),
                                    margin: const EdgeInsets.only(bottom: 12),
                                    decoration: BoxDecoration(
                                      color: Colors.red.shade50,
                                      borderRadius: BorderRadius.circular(12),
                                      border: Border.all(
                                        color: Colors.red.shade200,
                                      ),
                                    ),
                                    child: Row(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Icon(
                                          Icons.error_outline_rounded,
                                          color: Colors.red.shade700,
                                        ),
                                        const SizedBox(width: 10),
                                        Expanded(
                                          child: Text(
                                            _errorMessage!,
                                            style: TextStyle(
                                              color: Colors.red.shade700,
                                              fontSize: 14,
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                SizedBox(
                                  height: 52,
                                  child: FilledButton.icon(
                                    onPressed: _isLoading ? null : _submitLogin,
                                    icon: _isLoading
                                        ? const SizedBox(
                                            width: 18,
                                            height: 18,
                                            child: CircularProgressIndicator(
                                              strokeWidth: 2,
                                              color: Colors.white,
                                            ),
                                          )
                                        : const Icon(Icons.login_rounded),
                                    label: Text(
                                      _isLoading ? 'Signing in...' : 'Sign in',
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }
}

class BusListScreen extends StatefulWidget {
  const BusListScreen({super.key, required this.accessToken});

  final String accessToken;

  @override
  State<BusListScreen> createState() => _BusListScreenState();
}

class _BusListScreenState extends State<BusListScreen> {
  bool _isLoading = true;
  String? _errorMessage;
  List<Map<String, dynamic>> _buses = const [];

  @override
  void initState() {
    super.initState();
    _fetchBuses();
  }

  Future<void> _fetchBuses() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final response = await http.get(
        AppConfig.busesUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );

      if (!mounted) {
        return;
      }

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final decoded = jsonDecode(response.body) as List<dynamic>;
        final buses = decoded
            .map((item) => item as Map<String, dynamic>)
            .toList(growable: false);

        setState(() {
          _buses = buses;
          _isLoading = false;
        });
        return;
      }

      final errorBody = response.body.isNotEmpty
          ? jsonDecode(response.body)
          : <String, dynamic>{};
      final message = errorBody['detail'] ?? 'Unable to load buses.';
      setState(() {
        _errorMessage = message.toString();
        _isLoading = false;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Bus List'),
        actions: [
          IconButton(
            onPressed: _showAddBusScreen,
            icon: const Icon(Icons.add_circle_outline_rounded),
            tooltip: 'Add bus',
          ),
          IconButton(
            onPressed: _showBusMapScreen,
            icon: const Icon(Icons.map_outlined),
            tooltip: 'Bus map',
          ),
          IconButton(
            onPressed: _showDriverMode,
            icon: const Icon(Icons.drive_eta_rounded),
            tooltip: 'Driver mode',
          ),
          IconButton(
            onPressed: () => _signOut(context),
            icon: const Icon(Icons.logout_rounded),
            tooltip: 'Sign out',
          ),
        ],
      ),
      body: SafeArea(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _errorMessage != null
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.error_outline_rounded, size: 48),
                      const SizedBox(height: 16),
                      Text(
                        _errorMessage!,
                        textAlign: TextAlign.center,
                        style: const TextStyle(fontSize: 16),
                      ),
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed: _fetchBuses,
                        child: const Text('Retry'),
                      ),
                    ],
                  ),
                ),
              )
            : _buses.isEmpty
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.directions_bus_outlined, size: 56),
                      const SizedBox(height: 16),
                      const Text(
                        'No buses available.',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: 16),
                      ),
                      const SizedBox(height: 16),
                      FilledButton.icon(
                        onPressed: _showAddBusScreen,
                        icon: const Icon(Icons.add_rounded),
                        label: const Text('Add your first bus'),
                      ),
                    ],
                  ),
                ),
              )
            : RefreshIndicator(
                onRefresh: _fetchBuses,
                child: ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: _buses.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 12),
                  itemBuilder: (context, index) {
                    final bus = _buses[index];
                    return Card(
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text(
                                  bus['bus_number']?.toString() ??
                                      'Unknown bus',
                                  style: Theme.of(context).textTheme.titleLarge,
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 10,
                                    vertical: 6,
                                  ),
                                  decoration: BoxDecoration(
                                    color: _statusColor(
                                      bus['status']?.toString() ?? 'active',
                                    ),
                                    borderRadius: BorderRadius.circular(999),
                                  ),
                                  child: Text(
                                    bus['status']?.toString() ?? 'active',
                                    style: const TextStyle(
                                      color: Colors.white,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            _detailRow(
                              'License plate',
                              bus['license_plate']?.toString() ?? 'N/A',
                            ),
                            _detailRow('Capacity', '${bus['capacity'] ?? 0}'),
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ),
      ),
    );
  }

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'maintenance':
        return Colors.orange;
      case 'out_of_service':
        return Colors.red;
      default:
        return Colors.green;
    }
  }

  Widget _detailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          SizedBox(
            width: 110,
            child: Text(
              '$label:',
              style: const TextStyle(
                color: Colors.black54,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }

  Future<void> _showAddBusScreen() async {
    final created = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => AddBusScreen(accessToken: widget.accessToken),
      ),
    );

    if (created == true && mounted) {
      _fetchBuses();
    }
  }

  Future<void> _showBusMapScreen() async {
    if (!mounted) return;

    String busId = '';
    String busNumber = 'BUS-001';

    for (final bus in _buses) {
      final candidate = bus['bus_number']?.toString() ?? '';
      if (candidate.toUpperCase() == 'BUS-001') {
        busId = bus['id']?.toString() ?? '';
        busNumber = candidate;
        break;
      }
    }

    if (busId.isEmpty && _buses.isNotEmpty) {
      final firstBus = _buses.first;
      busId = firstBus['id']?.toString() ?? '';
      busNumber = firstBus['bus_number']?.toString() ?? busNumber;
    }

    if (busId.isEmpty) {
      setState(() {
        _errorMessage = 'No bus is available to show on the map.';
      });
      return;
    }

    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => BusMapScreen(
          accessToken: widget.accessToken,
          busId: busId,
          busNumber: busNumber,
        ),
      ),
    );
  }

  Future<void> _showDriverMode() async {
    if (!mounted) return;

    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => DriverModeScreen(
          accessToken: widget.accessToken,
          buses: _buses,
        ),
      ),
    );
  }
}

class BusMapScreen extends StatefulWidget {
  const BusMapScreen({
    super.key,
    required this.accessToken,
    required this.busId,
    required this.busNumber,
  });

  final String accessToken;
  final String busId;
  final String busNumber;

  @override
  State<BusMapScreen> createState() => _BusMapScreenState();
}

class _BusMapScreenState extends State<BusMapScreen> {
  bool _isLoading = true;
  late final Timer _timer;
  late final Timer _uiTickTimer;
  late final MapController _mapController;
  String? _errorMessage;
  LatLng? _location;
  DateTime? _lastUpdated;
  bool _followBus = true;
  bool _hasCenteredInitially = false;

  @override
  void initState() {
    super.initState();
    _mapController = MapController();
    _loadLatestGps();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (mounted) {
        _loadLatestGps();
      }
    });
    // Ticker every 5 seconds to update "X seconds/minutes ago"
    _uiTickTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (mounted && _lastUpdated != null) {
        setState(() {});
      }
    });
  }

  String _formatTimeAgo(DateTime dt) {
    final diff = DateTime.now().difference(dt);
    if (diff.inSeconds < 10) return 'Just now';
    if (diff.inSeconds < 60) return '${diff.inSeconds}s ago';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    return '${diff.inHours}h ago';
  }

  bool get _isStale {
    if (_lastUpdated == null) return false;
    return DateTime.now().difference(_lastUpdated!) > const Duration(minutes: 3);
  }

  Future<void> _loadLatestGps() async {
    if (!mounted) {
      return;
    }

    if (_location == null) {
      setState(() {
        _isLoading = true;
      });
    }

    try {
      final response = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/v1/buses/${widget.busId}/gps/latest'),
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );

      if (!mounted) {
        return;
      }

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final latitude = body['latitude'];
        final longitude = body['longitude'];

        if (latitude == null || longitude == null) {
          setState(() {
            _location = null;
            _errorMessage = null;
            _lastUpdated = null;
            _isLoading = false;
          });
          return;
        }

        final timestampValue = body['timestamp'];
        final nextLocation = LatLng(
          (latitude as num).toDouble(),
          (longitude as num).toDouble(),
        );
        final parsedTimestamp = timestampValue != null
            ? DateTime.tryParse(timestampValue.toString())
            : null;

        if (!mounted) {
          return;
        }

        setState(() {
          _location = nextLocation;
          _lastUpdated = parsedTimestamp?.toLocal();
          _errorMessage = null;
          _isLoading = false;
        });

        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted) {
            return;
          }
          if (!_hasCenteredInitially) {
            _hasCenteredInitially = true;
            _mapController.move(nextLocation, 16);
          } else if (_followBus) {
            _mapController.move(nextLocation, _mapController.camera.zoom);
          }
        });
        return;
      }

      final errorBody = response.body.isNotEmpty
          ? jsonDecode(response.body)
          : <String, dynamic>{};
      setState(() {
        _location = null;
        _errorMessage = (errorBody['detail'] ?? 'Unable to load bus location.').toString();
        _lastUpdated = null;
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }

      setState(() {
        _location = null;
        _errorMessage = 'Unable to connect to the server. Please try again.';
        _lastUpdated = null;
        _isLoading = false;
      });
    }
  }

  @override
  void dispose() {
    _timer.cancel();
    _uiTickTimer.cancel();
    _mapController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final mapContent = _location == null
        ? _buildCenteredState()
        : FlutterMap(
            mapController: _mapController,
            options: const MapOptions(
              initialCenter: LatLng(0, 0),
              initialZoom: 16,
            ),
            children: [
              TileLayer(
                urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.example.mobile_app',
              ),
              MarkerLayer(
                markers: [
                  Marker(
                    point: _location!,
                    width: 42,
                    height: 42,
                    child: const Icon(
                      Icons.location_on,
                      color: Color(0xFFF59E0B),
                      size: 34,
                    ),
                  ),
                ],
              ),
            ],
          );

    return Scaffold(
      appBar: AppBar(
        title: Text('${widget.busNumber} Map'),
        actions: [
          IconButton(
            icon: Icon(_followBus ? Icons.gps_fixed_rounded : Icons.gps_not_fixed_rounded),
            tooltip: _followBus ? 'Auto-following bus' : 'Follow disabled',
            onPressed: () {
              setState(() {
                _followBus = !_followBus;
                if (_followBus && _location != null) {
                  _mapController.move(_location!, _mapController.camera.zoom);
                }
              });
            },
          ),
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh location',
            onPressed: _loadLatestGps,
          ),
        ],
      ),
      floatingActionButton: _location != null
          ? FloatingActionButton(
              heroTag: 'recenter_bus_fab',
              onPressed: () {
                _mapController.move(_location!, 16);
                setState(() {
                  _followBus = true;
                });
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Centered on bus location (Follow enabled)'),
                    duration: Duration(seconds: 2),
                  ),
                );
              },
              tooltip: 'Recenter on bus',
              child: const Icon(Icons.my_location_rounded),
            )
          : null,
      body: SafeArea(
        child: Column(
          children: [
            if (_isStale)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                color: Colors.amber.shade100,
                child: Row(
                  children: [
                    Icon(Icons.warning_amber_rounded, color: Colors.amber.shade900, size: 20),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Location signal is stale (>3 min old). The bus may be offline or in a low coverage area.',
                        style: TextStyle(
                          color: Colors.amber.shade900,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            if (_lastUpdated != null)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                color: Colors.black.withValues(alpha: 8),
                child: Row(
                  children: [
                    Icon(
                      _isStale ? Icons.access_time_filled : Icons.check_circle_rounded,
                      size: 16,
                      color: _isStale ? Colors.amber.shade800 : Colors.green.shade700,
                    ),
                    const SizedBox(width: 8),
                    Text(
                      'Last updated: ${_formatTimeAgo(_lastUpdated!)} (${_lastUpdated!.hour.toString().padLeft(2, '0')}:${_lastUpdated!.minute.toString().padLeft(2, '0')}:${_lastUpdated!.second.toString().padLeft(2, '0')})',
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
                    ),
                    const Spacer(),
                    if (_followBus)
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xFFF59E0B).withValues(alpha: 30),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Text(
                          'FOLLOWING',
                          style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: Color(0xFFB45309)),
                        ),
                      ),
                  ],
                ),
              ),
            Expanded(
              child: _errorMessage != null
                  ? _buildCenteredState()
                  : mapContent,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCenteredState() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline_rounded, size: 48),
              const SizedBox(height: 16),
              Text(
                _errorMessage!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 16),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _loadLatestGps,
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.location_off_rounded, size: 52),
            SizedBox(height: 16),
            Text(
              'No location yet for this bus.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 16),
            ),
          ],
        ),
      ),
    );
  }
}

class DriverModeScreen extends StatefulWidget {
  const DriverModeScreen({
    super.key,
    required this.accessToken,
    required this.buses,
  });

  final String accessToken;
  final List<Map<String, dynamic>> buses;

  @override
  State<DriverModeScreen> createState() => _DriverModeScreenState();
}

class _DriverModeScreenState extends State<DriverModeScreen> {
  String? _selectedBusId;
  List<Map<String, dynamic>> _buses = [];

  bool get _hasActiveSubscription => context.read<DriverSharingController>().hasActiveSubscription;

  @override
  void initState() {
    super.initState();
    if (widget.buses.isNotEmpty) {
      _buses = List<Map<String, dynamic>>.from(widget.buses);
      _selectedBusId = _buses.first['id']?.toString();
    } else {
      _loadDriverBuses();
    }
  }

  Future<void> _loadDriverBuses() async {
    try {
      final response = await ColdStartHttpClient.get(
        AppConfig.busesUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
      );
      if (!mounted) return;
      if (response.statusCode >= 200 && response.statusCode < 300) {
        final decoded = jsonDecode(response.body) as List<dynamic>;
        final fetched = decoded.map((e) => e as Map<String, dynamic>).toList();
        setState(() {
          _buses = fetched;
          if (_buses.isNotEmpty) {
            _selectedBusId = _buses.first['id']?.toString();
          }
        });
      }
    } catch (_) {}
  }

  Future<void> _startSharing() async {
    if (_hasActiveSubscription) {
      return;
    }

    final busId = _selectedBusId;
    if (busId == null || busId.isEmpty) {
      final controller = context.read<DriverSharingController>();
      controller.stopSharing();
      return;
    }

    await context.read<DriverSharingController>().startSharing(
      busId: busId,
      accessToken: widget.accessToken,
    );
  }

  Future<void> _stopSharing() async {
    await context.read<DriverSharingController>().stopSharing();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<DriverSharingController>();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Driver mode'),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Icon(
                Icons.location_on_rounded,
                size: 60,
                color: Color(0xFFF59E0B),
              ),
              const SizedBox(height: 16),
              Text(
                'Share live bus location',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 24),
              DropdownButtonFormField<String>(
                initialValue: _selectedBusId,
                decoration: const InputDecoration(
                  labelText: 'Bus',
                  border: OutlineInputBorder(),
                ),
                items: _buses
                    .map(
                      (bus) => DropdownMenuItem<String>(
                        value: bus['id']?.toString(),
                        child: Text(
                          bus['bus_number']?.toString() ?? 'Bus',
                        ),
                      ),
                    )
                    .toList(),
                onChanged: (value) {
                  setState(() {
                    _selectedBusId = value;
                  });
                },
              ),
              const SizedBox(height: 20),
              if (controller.errorMessage != null)
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red.shade50,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.red.shade200),
                  ),
                  child: Text(
                    controller.errorMessage!,
                    style: TextStyle(color: Colors.red.shade700),
                  ),
                ),
              if (controller.lastUpdated != null) ...[
                const SizedBox(height: 12),
                Text(
                  controller.lastUpdated!,
                  style: TextStyle(color: Colors.green.shade700),
                ),
              ],
              const Spacer(),
              SizedBox(
                height: 52,
                child: FilledButton.icon(
                  onPressed: controller.isLoading
                      ? null
                      : (controller.hasActiveSubscription ? _stopSharing : _startSharing),
                  icon: controller.isLoading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : Icon(controller.hasActiveSubscription
                          ? Icons.stop_rounded
                          : Icons.play_arrow_rounded),
                  label: Text(
                    controller.isLoading
                        ? 'Sharing...'
                        : (controller.hasActiveSubscription ? 'Stop sharing' : 'Start sharing'),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class AddBusScreen extends StatefulWidget {
  const AddBusScreen({super.key, required this.accessToken});

  final String accessToken;

  @override
  State<AddBusScreen> createState() => _AddBusScreenState();
}

class _AddBusScreenState extends State<AddBusScreen> {
  final _formKey = GlobalKey<FormState>();
  final _busNumberController = TextEditingController();
  final _licensePlateController = TextEditingController();
  final _capacityController = TextEditingController();
  String _status = 'active';
  bool _isSaving = false;
  String? _errorMessage;

  String? _required(String? value, String label) {
    if (value == null || value.trim().isEmpty) {
      return '$label is required';
    }
    return null;
  }

  String? _capacityValidator(String? value) {
    final capacity = int.tryParse(value?.trim() ?? '');
    if (capacity == null || capacity < 1) {
      return 'Enter a capacity of at least 1';
    }
    return null;
  }

  Future<void> _saveBus() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isSaving = true;
      _errorMessage = null;
    });

    try {
      final response = await http.post(
        AppConfig.busesUri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Authorization': 'Bearer ${widget.accessToken}',
        },
        body: jsonEncode({
          'bus_number': _busNumberController.text.trim(),
          'license_plate': _licensePlateController.text.trim(),
          'capacity': int.parse(_capacityController.text.trim()),
          'status': _status,
        }),
      );

      if (!mounted) return;

      if (response.statusCode >= 200 && response.statusCode < 300) {
        Navigator.of(context).pop(true);
        return;
      }

      final body = response.body.isNotEmpty
          ? jsonDecode(response.body)
          : <String, dynamic>{};
      setState(() {
        _errorMessage = (body['detail'] ?? 'Unable to create the bus.')
            .toString();
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Unable to connect to the server. Please try again.';
      });
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Add bus')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Icon(
                      Icons.directions_bus_rounded,
                      size: 56,
                      color: Color(0xFFF59E0B),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      'Add a bus',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 28),
                    TextFormField(
                      controller: _busNumberController,
                      textInputAction: TextInputAction.next,
                      decoration: const InputDecoration(
                        labelText: 'Bus number',
                        border: OutlineInputBorder(),
                      ),
                      validator: (value) => _required(value, 'Bus number'),
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _licensePlateController,
                      textInputAction: TextInputAction.next,
                      decoration: const InputDecoration(
                        labelText: 'License plate',
                        border: OutlineInputBorder(),
                      ),
                      validator: (value) => _required(value, 'License plate'),
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _capacityController,
                      keyboardType: TextInputType.number,
                      textInputAction: TextInputAction.done,
                      decoration: const InputDecoration(
                        labelText: 'Capacity',
                        border: OutlineInputBorder(),
                      ),
                      validator: _capacityValidator,
                      onFieldSubmitted: (_) => _saveBus(),
                    ),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<String>(
                      initialValue: _status,
                      decoration: const InputDecoration(
                        labelText: 'Status',
                        border: OutlineInputBorder(),
                      ),
                      items: const [
                        DropdownMenuItem(
                          value: 'active',
                          child: Text('Active'),
                        ),
                        DropdownMenuItem(
                          value: 'maintenance',
                          child: Text('Maintenance'),
                        ),
                        DropdownMenuItem(
                          value: 'out_of_service',
                          child: Text('Out of service'),
                        ),
                      ],
                      onChanged: _isSaving
                          ? null
                          : (value) =>
                                setState(() => _status = value ?? 'active'),
                    ),
                    if (_errorMessage != null) ...[
                      const SizedBox(height: 16),
                      Text(
                        _errorMessage!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ],
                    const SizedBox(height: 24),
                    SizedBox(
                      height: 52,
                      child: FilledButton.icon(
                        onPressed: _isSaving ? null : _saveBus,
                        icon: _isSaving
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Icon(Icons.save_rounded),
                        label: Text(_isSaving ? 'Saving...' : 'Save bus'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _busNumberController.dispose();
    _licensePlateController.dispose();
    _capacityController.dispose();
    super.dispose();
  }
}
