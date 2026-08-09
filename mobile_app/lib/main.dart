import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import 'config/app_config.dart';

const _secureTokenKey = 'access_token';
const _secureRoleKey = 'user_role';
final _secureStorage = FlutterSecureStorage();

Future<void> _signOut(BuildContext context) async {
  await _secureStorage.delete(key: _secureTokenKey);
  await _secureStorage.delete(key: _secureRoleKey);
  if (!context.mounted) return;
  Navigator.of(context).pushAndRemoveUntil(
    MaterialPageRoute(builder: (_) => const LoginScreen()),
    (route) => false,
  );
}

void main() {
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
    notifyListeners();

    try {
      final hasPermission = await _requestLocationPermission();
      if (!hasPermission) {
        _errorMessage = 'Location permission is required to share GPS data.';
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
        if (_positionSubscription == null || !_isSharing) {
          return;
        }

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
            notifyListeners();
            return;
          }

          final body = response.body.isNotEmpty
              ? jsonDecode(response.body)
              : <String, dynamic>{};
          _errorMessage =
              (body['detail'] ?? 'Unable to share location.').toString();
          notifyListeners();
        } catch (_) {
          _errorMessage = 'Unable to send your current location.';
          notifyListeners();
        }
      });

      _isSharing = true;
      _isLoading = false;
      notifyListeners();
    } catch (_) {
      _errorMessage = 'Unable to fetch your current location.';
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
    notifyListeners();
  }

  Future<bool> _requestLocationPermission() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      return false;
    }

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }

    return permission == LocationPermission.whileInUse ||
        permission == LocationPermission.always;
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
  String? _errorMessage;

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
      final response = await http.get(
        AppConfig.authMeUri,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer $accessToken',
        },
      );

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final data = response.body.isNotEmpty
            ? jsonDecode(response.body) as Map<String, dynamic>
            : <String, dynamic>{};
        final role = data['role']?.toString() ?? 'parent';
        await _secureStorage.write(key: _secureRoleKey, value: role);
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
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
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
      case 'teacher':
        return BusListScreen(accessToken: accessToken);
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

class ParentHomeScreen extends StatelessWidget {
  const ParentHomeScreen({
    super.key,
    required this.accessToken,
  });

  final String accessToken;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Parent Portal'),
        actions: [
          IconButton(
            onPressed: () => _signOut(context),
            icon: const Icon(Icons.logout_rounded),
            tooltip: 'Sign out',
          ),
        ],
      ),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: const [
              Icon(Icons.person_outline_rounded, size: 72, color: Color(0xFFF59E0B)),
              SizedBox(height: 20),
              Text(
                'Welcome to the parent portal.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              SizedBox(height: 12),
              Text(
                'Your child and bus details are available through the admin dashboard.',
                textAlign: TextAlign.center,
              ),
            ],
          ),
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
      _errorMessage = null;
    });

    try {
      final response = await http.post(
        AppConfig.authLoginUri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: jsonEncode({
          'email': _emailController.text.trim(),
          'password': _passwordController.text,
        }),
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
                                color: Colors.white.withOpacity(0.18),
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
                                color: Colors.white.withOpacity(0.9),
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
                                const SizedBox(height: 18),
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
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
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
  late final MapController _mapController;
  String? _errorMessage;
  LatLng? _location;
  DateTime? _lastUpdated;

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
          _mapController.move(nextLocation, 16);
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
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (_lastUpdated != null)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                color: Colors.black.withOpacity(0.03),
                child: Text(
                  'Last updated: ${_lastUpdated!.toLocal().toString()}',
                  style: const TextStyle(fontWeight: FontWeight.w600),
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

  bool get _hasActiveSubscription => context.read<DriverSharingController>().hasActiveSubscription;

  @override
  void initState() {
    super.initState();
    _selectedBusId = widget.buses.isNotEmpty
        ? widget.buses.first['id']?.toString()
        : null;
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
                value: _selectedBusId,
                decoration: const InputDecoration(
                  labelText: 'Bus',
                  border: OutlineInputBorder(),
                ),
                items: widget.buses
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
                      value: _status,
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
