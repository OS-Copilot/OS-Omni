import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../app/app_state.dart';
import '../../../shared/models/models.dart';
import '../../../shared/widgets/app_widgets.dart';

class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const ScreenContainer(child: AppLoading());
  }
}

class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key});

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  UserRole _role = UserRole.rider;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final canCreateAccount = _role != UserRole.admin;
    final form = _AuthFormPanel(
      role: _role,
      name: _name,
      email: _email,
      password: _password,
      canCreateAccount: canCreateAccount,
      isLoading: state.isLoading,
      errorMessage: state.errorMessage,
      onRoleChanged: (role) {
        setState(() => _role = role);
      },
      onLogin: () => state.login(
        _email.text.trim(),
        _password.text,
        _role,
      ),
      onRegister: () => state.register(
        _name.text.trim(),
        _email.text.trim(),
        _password.text,
        _role,
      ),
    );
    return ScreenContainer(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 900;
          final contentHeight = (constraints.maxHeight - (compact ? 32 : 56))
              .clamp(520.0, 760.0)
              .toDouble();
          final brandHeight = compact ? 430.0 : contentHeight;
          return Container(
            color: const Color(0xFFEEF4F8),
            child: SafeArea(
              child: SingleChildScrollView(
                padding: EdgeInsets.symmetric(
                  horizontal: compact ? 16 : 28,
                  vertical: compact ? 16 : 28,
                ),
                child: ConstrainedBox(
                  constraints: BoxConstraints(minHeight: contentHeight),
                  child: Center(
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 1180),
                      child: compact
                          ? Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                SizedBox(
                                  height: brandHeight,
                                  child: _AuthBrandPanel(role: _role),
                                ),
                                const SizedBox(height: 18),
                                form,
                              ],
                            )
                          : SizedBox(
                              height: contentHeight,
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.stretch,
                                children: [
                                  Expanded(
                                    flex: 5,
                                    child: _AuthBrandPanel(role: _role),
                                  ),
                                  const SizedBox(width: 18),
                                  Expanded(flex: 4, child: form),
                                ],
                              ),
                            ),
                    ),
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _AuthBrandPanel extends StatelessWidget {
  const _AuthBrandPanel({required this.role});

  final UserRole role;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      constraints: const BoxConstraints(minHeight: 430),
      decoration: BoxDecoration(
        color: const Color(0xFF132238),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
        boxShadow: const [
          BoxShadow(
            blurRadius: 24,
            offset: Offset(0, 14),
            color: Color(0x1F0F172A),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(
            child: CustomPaint(
              painter: _AuthMapPainter(
                accent: _roleAccent(role),
                grid: Colors.white.withValues(alpha: 0.08),
              ),
            ),
          ),
          Positioned(
            right: -80,
            top: -110,
            child: Container(
              width: 260,
              height: 260,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: _roleAccent(role).withValues(alpha: 0.22),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(28),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 46,
                      height: 46,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Icon(
                        Icons.route,
                        color: _roleAccent(role),
                        size: 28,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Text(
                      'opendriver',
                      style: theme.textTheme.headlineSmall?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
                const Spacer(),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: Colors.white.withValues(alpha: 0.14),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _roleTitle(role),
                        style: theme.textTheme.headlineMedium?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.w900,
                          height: 1.05,
                        ),
                      ),
                      const SizedBox(height: 14),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          _AuthStatusPill(
                            icon: Icons.near_me,
                            label: 'Dispatch ready',
                            color: _roleAccent(role),
                          ),
                          _AuthStatusPill(
                            icon: Icons.payments,
                            label: 'Payments synced',
                            color: const Color(0xFF22C55E),
                          ),
                          _AuthStatusPill(
                            icon: Icons.security,
                            label: 'Secure session',
                            color: const Color(0xFFF59E0B),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AuthFormPanel extends StatelessWidget {
  const _AuthFormPanel({
    required this.role,
    required this.name,
    required this.email,
    required this.password,
    required this.canCreateAccount,
    required this.isLoading,
    required this.onRoleChanged,
    required this.onLogin,
    required this.onRegister,
    this.errorMessage,
  });

  final UserRole role;
  final TextEditingController name;
  final TextEditingController email;
  final TextEditingController password;
  final bool canCreateAccount;
  final bool isLoading;
  final String? errorMessage;
  final ValueChanged<UserRole> onRoleChanged;
  final VoidCallback onLogin;
  final VoidCallback onRegister;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(28),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFE2E8F0)),
        boxShadow: const [
          BoxShadow(
            blurRadius: 24,
            offset: Offset(0, 14),
            color: Color(0x170F172A),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Sign in',
            style: theme.textTheme.headlineMedium?.copyWith(
              fontWeight: FontWeight.w900,
              color: const Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Choose a workspace and continue.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: const Color(0xFF64748B),
            ),
          ),
          const SizedBox(height: 22),
          SegmentedButton<UserRole>(
            segments: const [
              ButtonSegment(
                value: UserRole.rider,
                label: Text('Rider'),
                icon: Icon(Icons.person),
              ),
              ButtonSegment(
                value: UserRole.driver,
                label: Text('Driver'),
                icon: Icon(Icons.local_taxi),
              ),
              ButtonSegment(
                value: UserRole.admin,
                label: Text('Admin'),
                icon: Icon(Icons.admin_panel_settings),
              ),
            ],
            selected: {role},
            onSelectionChanged: (value) => onRoleChanged(value.first),
          ),
          const SizedBox(height: 18),
          _AuthTextField(
            controller: name,
            label: 'Name',
            icon: Icons.badge_outlined,
          ),
          const SizedBox(height: 12),
          _AuthTextField(
            controller: email,
            label: 'Email',
            icon: Icons.mail_outline,
            keyboardType: TextInputType.emailAddress,
          ),
          const SizedBox(height: 12),
          _AuthTextField(
            controller: password,
            label: 'Password',
            icon: Icons.lock_outline,
            obscureText: true,
          ),
          const SizedBox(height: 16),
          if (errorMessage != null) ...[
            ErrorBanner(errorMessage!),
            const SizedBox(height: 12),
          ],
          FilledButton.icon(
            onPressed: isLoading ? null : onLogin,
            icon: isLoading
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.login),
            label: const Text('Login'),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: isLoading || !canCreateAccount ? null : onRegister,
            icon: Icon(
              canCreateAccount
                  ? Icons.person_add_alt_1
                  : Icons.admin_panel_settings,
            ),
            label: Text(
              canCreateAccount
                  ? 'Create account'
                  : 'Admin accounts are invite-only',
            ),
          ),
        ],
      ),
    );
  }
}

class _AuthTextField extends StatelessWidget {
  const _AuthTextField({
    required this.controller,
    required this.label,
    required this.icon,
    this.keyboardType,
    this.obscureText = false,
  });

  final TextEditingController controller;
  final String label;
  final IconData icon;
  final TextInputType? keyboardType;
  final bool obscureText;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      obscureText: obscureText,
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon),
        filled: true,
        fillColor: const Color(0xFFF8FAFC),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: Color(0xFFCBD5E1)),
        ),
      ),
    );
  }
}

class _AuthStatusPill extends StatelessWidget {
  const _AuthStatusPill({
    required this.icon,
    required this.label,
    required this.color,
  });

  final IconData icon;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Colors.white.withValues(alpha: 0.16)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _AuthMapPainter extends CustomPainter {
  const _AuthMapPainter({required this.accent, required this.grid});

  final Color accent;
  final Color grid;

  @override
  void paint(Canvas canvas, Size size) {
    final gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    for (var x = -size.height; x < size.width + size.height; x += 54) {
      canvas.drawLine(
          Offset(x, 0), Offset(x + size.height, size.height), gridPaint);
    }
    for (var y = 40.0; y < size.height; y += 64) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y - 50), gridPaint);
    }

    final route = Path()
      ..moveTo(size.width * 0.12, size.height * 0.72)
      ..cubicTo(
        size.width * 0.28,
        size.height * 0.58,
        size.width * 0.28,
        size.height * 0.30,
        size.width * 0.48,
        size.height * 0.38,
      )
      ..cubicTo(
        size.width * 0.65,
        size.height * 0.45,
        size.width * 0.66,
        size.height * 0.20,
        size.width * 0.86,
        size.height * 0.24,
      );

    canvas.drawPath(
      route,
      Paint()
        ..color = Colors.white.withValues(alpha: 0.18)
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 18,
    );
    canvas.drawPath(
      route,
      Paint()
        ..color = accent
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 7,
    );

    final markerPaint = Paint()..color = Colors.white;
    final markerStroke = Paint()
      ..color = accent
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4;
    for (final point in [
      Offset(size.width * 0.12, size.height * 0.72),
      Offset(size.width * 0.48, size.height * 0.38),
      Offset(size.width * 0.86, size.height * 0.24),
    ]) {
      canvas.drawCircle(point, 12, markerPaint);
      canvas.drawCircle(point, 12, markerStroke);
    }
  }

  @override
  bool shouldRepaint(covariant _AuthMapPainter oldDelegate) {
    return oldDelegate.accent != accent || oldDelegate.grid != grid;
  }
}

Color _roleAccent(UserRole role) {
  return switch (role) {
    UserRole.rider => const Color(0xFF2563EB),
    UserRole.driver => const Color(0xFF0891B2),
    UserRole.admin => const Color(0xFF7C3AED),
  };
}

String _roleTitle(UserRole role) {
  return switch (role) {
    UserRole.rider => 'Rider access',
    UserRole.driver => 'Driver access',
    UserRole.admin => 'Admin access',
  };
}

class UnauthorizedScreen extends StatelessWidget {
  const UnauthorizedScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const ScreenContainer(
      title: 'Unauthorized',
      child: Center(child: Text('This account cannot access that workspace.')),
    );
  }
}
