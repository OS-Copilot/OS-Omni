import 'package:flutter/material.dart';

class AppBreakpoints {
  static const mobile = 640.0;
  static const tablet = 960.0;
  static const desktop = 1200.0;
}

class AdaptiveLayout extends StatelessWidget {
  const AdaptiveLayout({
    required this.mobile,
    required this.desktop,
    this.tablet,
    super.key,
  });

  final Widget mobile;
  final Widget? tablet;
  final Widget desktop;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    if (width >= AppBreakpoints.tablet) return desktop;
    if (width >= AppBreakpoints.mobile) return tablet ?? desktop;
    return mobile;
  }
}

class ResponsiveTwoColumnLayout extends StatelessWidget {
  const ResponsiveTwoColumnLayout({
    required this.primary,
    required this.secondary,
    super.key,
  });

  final Widget primary;
  final Widget secondary;

  @override
  Widget build(BuildContext context) {
    return AdaptiveLayout(
      mobile: ListView(
        padding: const EdgeInsets.all(16),
        children: [primary, const SizedBox(height: 16), secondary],
      ),
      desktop: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 2,
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [primary],
            ),
          ),
          const SizedBox(width: 20),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(0, 20, 20, 20),
              children: [secondary],
            ),
          ),
        ],
      ),
    );
  }
}
