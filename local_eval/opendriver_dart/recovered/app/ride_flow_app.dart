import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../features/admin/presentation/admin_screens.dart';
import '../features/auth/presentation/auth_screens.dart';
import '../features/driver/presentation/driver_screens.dart';
import '../features/rider/presentation/rider_screens.dart';
import '../shared/models/models.dart';
import '../shared/theme/app_theme.dart';
import 'app_state.dart';

class opendriverApp extends StatefulWidget {
  const opendriverApp({super.key});

  @override
  State<opendriverApp> createState() => _opendriverAppState();
}

class _opendriverAppState extends State<opendriverApp> {
  late final GoRouter _router;

  @override
  void initState() {
    super.initState();
    final state = context.read<AppState>();
    _router = GoRouter(
      refreshListenable: state,
      initialLocation: '/auth',
      redirect: (context, routerState) {
        final user = state.currentUser;
        final path = routerState.uri.path;
        if (user == null) return path == '/auth' ? null : '/auth';
        if (path == '/auth' || path == '/') {
          return switch (user.role) {
            UserRole.rider => '/rider',
            UserRole.driver => '/driver',
            UserRole.admin => '/admin',
          };
        }
        if (path.startsWith('/rider') && user.role != UserRole.rider) {
          return '/';
        }
        if (path.startsWith('/driver') && user.role != UserRole.driver) {
          return '/';
        }
        if (path.startsWith('/admin') && user.role != UserRole.admin) {
          return '/';
        }
        return null;
      },
      routes: [
        GoRoute(path: '/', builder: (_, __) => const SplashScreen()),
        GoRoute(path: '/auth', builder: (_, __) => const WelcomeScreen()),
        GoRoute(path: '/rider', builder: (_, __) => const RiderHomeScreen()),
        GoRoute(path: '/driver', builder: (_, __) => const DriverHomeScreen()),
        GoRoute(
          path: '/admin',
          builder: (_, __) => const AdminDashboardScreen(),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'opendriver',
      theme: buildAppTheme(),
      debugShowCheckedModeBanner: false,
      routerConfig: _router,
    );
  }
}
