import 'package:flutter/material.dart';

import '../models/models.dart';
import '../theme/app_theme.dart';
import '../utils/ride_math.dart';

class ScreenContainer extends StatelessWidget {
  const ScreenContainer({
    required this.child,
    this.title,
    this.actions,
    super.key,
  });

  final Widget child;
  final String? title;
  final List<Widget>? actions;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: title == null
          ? null
          : AppBar(title: Text(title!), actions: actions),
      body: SafeArea(child: child),
    );
  }
}

class AppCard extends StatelessWidget {
  const AppCard({
    required this.child,
    this.padding = const EdgeInsets.all(16),
    super.key,
  });

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(padding: padding, child: child),
    );
  }
}

class AppTextField extends StatelessWidget {
  const AppTextField({
    required this.controller,
    required this.label,
    this.keyboardType,
    this.obscureText = false,
    this.minLines,
    this.maxLines = 1,
    this.onChanged,
    super.key,
  });

  final TextEditingController controller;
  final String label;
  final TextInputType? keyboardType;
  final bool obscureText;
  final int? minLines;
  final int maxLines;
  final ValueChanged<String>? onChanged;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      obscureText: obscureText,
      minLines: obscureText ? 1 : minLines,
      maxLines: obscureText ? 1 : maxLines,
      onChanged: onChanged,
      decoration: InputDecoration(
        labelText: label,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
        filled: true,
        fillColor: Colors.white,
      ),
    );
  }
}

class StarRatingInput extends StatelessWidget {
  const StarRatingInput({
    required this.value,
    required this.onChanged,
    this.label = 'Rating',
    super.key,
  });

  final int value;
  final ValueChanged<int> onChanged;
  final String label;

  @override
  Widget build(BuildContext context) {
    final selectedValue = value.clamp(0, 5).toInt();
    return Semantics(
      label: selectedValue == 0
          ? '$label: no rating selected'
          : '$label: $selectedValue of 5 stars',
      child: Center(
        child: FittedBox(
          fit: BoxFit.scaleDown,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (var star = 1; star <= 5; star += 1)
                Tooltip(
                  message: '$star star${star == 1 ? '' : 's'}',
                  child: Semantics(
                    button: true,
                    selected: star <= selectedValue,
                    label: 'Rate $star star${star == 1 ? '' : 's'}',
                    child: IconButton(
                      key: ValueKey('star-rating-$star'),
                      iconSize: 36,
                      color: star <= selectedValue
                          ? const Color(0xFFF59E0B)
                          : Colors.grey.shade400,
                      icon: const Icon(Icons.star),
                      onPressed: () => onChanged(star),
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

class EmptyState extends StatelessWidget {
  const EmptyState(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Text(
        message,
        style: Theme.of(
          context,
        ).textTheme.bodyMedium?.copyWith(color: AppColors.muted),
      ),
    );
  }
}

class AppLoading extends StatelessWidget {
  const AppLoading({super.key});

  @override
  Widget build(BuildContext context) {
    return const Center(child: CircularProgressIndicator());
  }
}

class RideStatusBadge extends StatelessWidget {
  const RideStatusBadge(this.status, {super.key});

  final String status;

  @override
  Widget build(BuildContext context) {
    return Chip(
      label: Text(status.replaceAll('_', ' ')),
      backgroundColor: AppColors.accent.withValues(alpha: 0.12),
      labelStyle: const TextStyle(
        color: AppColors.accent,
        fontWeight: FontWeight.w800,
      ),
      side: BorderSide.none,
    );
  }
}

class RideTimeline extends StatelessWidget {
  const RideTimeline({
    required this.status,
    this.entries = const [],
    super.key,
  });

  final String status;
  final List<RideTimelineEntry> entries;

  @override
  Widget build(BuildContext context) {
    const steps = [
      'scheduled',
      'requested',
      'searching',
      'accepted',
      'driver_arriving',
      'arrived',
      'in_progress',
      'completed',
    ];
    final activeIndex = steps.indexOf(status);
    return Column(
      children: [
        for (var i = 0; i < steps.length; i++)
          ListTile(
            dense: true,
            leading: CircleAvatar(
              radius: 10,
              backgroundColor: i <= activeIndex
                  ? AppColors.accent
                  : Colors.grey.shade300,
            ),
            title: Text(steps[i].replaceAll('_', ' ')),
            subtitle: entries.where((entry) => entry.status == steps[i]).isEmpty
                ? null
                : Text(
                    entries
                        .where((entry) => entry.status == steps[i])
                        .last
                        .label,
                  ),
          ),
      ],
    );
  }
}

class FareBreakdownCard extends StatelessWidget {
  const FareBreakdownCard({required this.fare, super.key});

  final FareBreakdown fare;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Fare estimate', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          _textLine('Ride type', fare.rideTierTitle),
          _line('Base fare', fare.baseFare),
          _line('Distance', fare.distanceFare),
          _line('Time', fare.timeFare),
          _line('Service fee', fare.serviceFee),
          if (fare.waypointFee != 0) _line('Stops', fare.waypointFee),
          if (fare.pickupTimeAdjustment != 0)
            _line(
              fare.pickupTimeLabel.isEmpty
                  ? 'Pickup time'
                  : 'Pickup time (${fare.pickupTimeLabel})',
              fare.pickupTimeAdjustment,
            ),
          if (fare.discountAmount > 0)
            _line('Promo ${fare.promoCode}', -fare.discountAmount),
          const Divider(),
          _line('Estimated total', fare.estimatedTotal, bold: true),
        ],
      ),
    );
  }

  Widget _line(String label, double value, {bool bold = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label),
          Text(
            formatMoney(
              value,
              currencySymbol: fare.currencySymbol,
              currencyCode: fare.currencyCode,
              currencyDecimals: fare.currencyDecimals,
            ),
            style: TextStyle(
              fontWeight: bold ? FontWeight.w900 : FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  Widget _textLine(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class DriverInfoCard extends StatelessWidget {
  const DriverInfoCard({
    required this.ride,
    this.onMessage,
    this.onSafety,
    super.key,
  });

  final Ride ride;
  final VoidCallback? onMessage;
  final VoidCallback? onSafety;

  @override
  Widget build(BuildContext context) {
    final driver = ride.driver;
    final profile = ride.driverProfile;
    if (!ride.hasConfirmedDriver || driver == null || profile == null) {
      return DecoratedBox(
        decoration: BoxDecoration(
          color: AppColors.soft,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppColors.accent.withValues(alpha: 0.14)),
        ),
        child: const Padding(
          padding: EdgeInsets.all(16),
          child: Row(
            children: [
              CircleAvatar(
                backgroundColor: Color(0xFFE0E7FF),
                child: Icon(Icons.radar, color: AppColors.accent),
              ),
              SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Matching your driver',
                      style: TextStyle(fontWeight: FontWeight.w900),
                    ),
                    SizedBox(height: 4),
                    Text(
                      'Driver and vehicle details appear after acceptance.',
                      style: TextStyle(
                        color: AppColors.muted,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    }

    final vehicle =
        '${profile.vehicleYear} ${profile.vehicleColor} ${profile.vehicleMake} ${profile.vehicleModel}';
    final pickupDistanceKm = calculateHaversineDistance(
      startLatitude: profile.currentLatitude,
      startLongitude: profile.currentLongitude,
      endLatitude: ride.pickupLatitude,
      endLongitude: ride.pickupLongitude,
    );
    final pickupEta = (pickupDistanceKm / 22 * 60).clamp(1, 25).ceil();

    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.grey.shade200),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _DriverAvatar(name: driver.name),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        driver.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Wrap(
                        spacing: 8,
                        runSpacing: 6,
                        children: [
                          _InfoPill(
                            icon: Icons.star,
                            label:
                                '${profile.averageRating.toStringAsFixed(2)} rating',
                          ),
                          _InfoPill(
                            icon: Icons.check_circle,
                            label: '${profile.totalTrips} trips',
                          ),
                          _InfoPill(
                            icon: Icons.near_me,
                            label: '$pickupEta min away',
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                const _VehicleGlyph(),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        vehicle,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w900),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'Verified vehicle',
                        style: TextStyle(
                          color: AppColors.muted,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                _LicensePlate(plate: profile.licensePlate),
              ],
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _DriverActionChip(
                  icon: Icons.phone,
                  label: driver.phone.isEmpty
                      ? 'Call'
                      : 'Call ${_maskPhone(driver.phone)}',
                  onPressed: () => _showCallSheet(
                    context,
                    driver.name,
                    driver.phone.isEmpty ? 'the driver' : driver.phone,
                  ),
                ),
                _DriverActionChip(
                  icon: Icons.chat_bubble_outline,
                  label: 'Message',
                  onPressed: onMessage,
                ),
                _DriverActionChip(
                  icon: Icons.shield_outlined,
                  label: 'Safety',
                  onPressed: onSafety ?? () => _showSafetySheet(context),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _maskPhone(String phone) {
    final digits = phone.replaceAll(RegExp(r'\D'), '');
    if (digits.length < 4) return phone;
    return '***-${digits.substring(digits.length - 4)}';
  }

  void _showCallSheet(BuildContext context, String driverName, String phone) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Call $driverName'),
        content: Text(
          'Call started through opendriver. Your personal phone number stays private. Contact: $phone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  void _showSafetySheet(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Trip safety'),
        content: const Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Confirm the license plate before entering the vehicle.'),
            SizedBox(height: 8),
            Text('Share trip status with a trusted contact.'),
            SizedBox(height: 8),
            Text('Use emergency help if the trip feels unsafe.'),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }
}

class _DriverAvatar extends StatelessWidget {
  const _DriverAvatar({required this.name});

  final String name;

  @override
  Widget build(BuildContext context) {
    final initial = name.trim().isEmpty ? 'D' : name.trim()[0].toUpperCase();
    return CircleAvatar(
      radius: 28,
      backgroundColor: AppColors.ink,
      child: Text(
        initial,
        style: const TextStyle(
          color: Colors.white,
          fontSize: 22,
          fontWeight: FontWeight.w900,
        ),
      ),
    );
  }
}

class _VehicleGlyph extends StatelessWidget {
  const _VehicleGlyph();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 64,
      height: 44,
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(16),
      ),
      child: const Icon(
        Icons.directions_car_filled,
        color: Colors.white,
        size: 30,
      ),
    );
  }
}

class _LicensePlate extends StatelessWidget {
  const _LicensePlate({required this.plate});

  final String plate;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minWidth: 92),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.ink, width: 1.4),
      ),
      child: Text(
        plate,
        textAlign: TextAlign.center,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
          color: AppColors.ink,
          fontWeight: FontWeight.w900,
          letterSpacing: 1.2,
        ),
      ),
    );
  }
}

class _InfoPill extends StatelessWidget {
  const _InfoPill({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.soft,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: AppColors.accent),
          const SizedBox(width: 5),
          Text(
            label,
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }
}

class _DriverActionChip extends StatelessWidget {
  const _DriverActionChip({
    required this.icon,
    required this.label,
    required this.onPressed,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: onPressed,
      icon: Icon(icon, size: 18),
      label: Text(label),
    );
  }
}

class TripCard extends StatelessWidget {
  const TripCard({required this.ride, this.onTap, super.key});

  final Ride ride;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const CircleAvatar(child: Icon(Icons.route)),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    ride.pickupAddress,
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                  for (
                    var index = 0;
                    index < ride.waypoints.length;
                    index += 1
                  ) ...[
                    const SizedBox(height: 4),
                    Text(
                      'Stop ${index + 1}: ${ride.waypoints[index].address}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ],
                  const SizedBox(height: 4),
                  Text(
                    ride.destinationAddress,
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '${ride.estimatedDistance.toStringAsFixed(1)} km - ${ride.estimatedDuration} min',
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  formatMoney(
                    ride.finalFare ?? ride.estimatedFare,
                    currencySymbol: ride.currencySymbol,
                    currencyCode: ride.currencyCode,
                    currencyDecimals: ride.currencyDecimals,
                  ),
                  style: const TextStyle(fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 6),
                RideStatusBadge(ride.status),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class ErrorBanner extends StatelessWidget {
  const ErrorBanner(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.danger.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.danger.withValues(alpha: 0.2)),
      ),
      child: Text(
        message,
        style: const TextStyle(
          color: AppColors.danger,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class MetricCard extends StatelessWidget {
  const MetricCard({
    required this.label,
    required this.value,
    this.icon = Icons.analytics,
    super.key,
  });

  final String label;
  final Object? value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 180,
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: AppColors.accent),
            const SizedBox(height: 10),
            Text(label, style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 6),
            Text(
              '${value ?? 0}',
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900),
            ),
          ],
        ),
      ),
    );
  }
}

class ReceiptCard extends StatelessWidget {
  const ReceiptCard({required this.ride, super.key});

  final Ride ride;

  @override
  Widget build(BuildContext context) {
    final fare = ride.fareBreakdown;
    final payment = ride.payment;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Receipt', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          _row('Ride', ride.id),
          _row('Pickup', ride.pickupAddress),
          for (var index = 0; index < ride.waypoints.length; index += 1)
            _row('Stop ${index + 1}', ride.waypoints[index].address),
          _row('Destination', ride.destinationAddress),
          _row('Driver', ride.driver?.name ?? 'Unassigned'),
          if (ride.status == 'scheduled') _row('Status', 'Scheduled'),
          _row(
            'Vehicle',
            ride.driverProfile == null
                ? 'Not available'
                : '${ride.driverProfile!.vehicleColor} ${ride.driverProfile!.vehicleMake} ${ride.driverProfile!.vehicleModel}',
          ),
          _row(
            'Distance',
            '${(ride.finalDistance ?? ride.estimatedDistance).toStringAsFixed(1)} km',
          ),
          _row(
            'Duration',
            '${ride.finalDuration ?? ride.estimatedDuration} min',
          ),
          if (fare != null) ...[
            const Divider(),
            _row('Base', _formatFare(fare.baseFare)),
            _row('Distance fare', _formatFare(fare.distanceFare)),
            _row('Time fare', _formatFare(fare.timeFare)),
            _row('Service fee', _formatFare(fare.serviceFee)),
            if (fare.waypointFee != 0)
              _row('Stops', _formatFare(fare.waypointFee)),
            if (fare.pickupTimeAdjustment != 0)
              _row(
                fare.pickupTimeLabel.isEmpty
                    ? 'Pickup time'
                    : 'Pickup time (${fare.pickupTimeLabel})',
                _formatFare(fare.pickupTimeAdjustment),
              ),
            if (fare.discountAmount > 0)
              _row(
                'Promo ${fare.promoCode}',
                _formatFare(-fare.discountAmount),
              ),
          ],
          const Divider(),
          _row(
            'Payment',
            payment == null
                ? ride.paymentStatus
                : '${payment.paymentMethod} - ${payment.status}',
          ),
          _row(
            'Total',
            formatMoney(
              ride.finalFare ?? ride.estimatedFare,
              currencySymbol: ride.currencySymbol,
              currencyCode: ride.currencyCode,
              currencyDecimals: ride.currencyDecimals,
            ),
            bold: true,
          ),
        ],
      ),
    );
  }

  Widget _row(String label, String value, {bool bold = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 110,
            child: Text(label, style: const TextStyle(color: AppColors.muted)),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                fontWeight: bold ? FontWeight.w900 : FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _formatFare(double value) {
    final fare = ride.fareBreakdown;
    return formatMoney(
      value,
      currencySymbol: fare?.currencySymbol ?? ride.currencySymbol,
      currencyCode: fare?.currencyCode ?? ride.currencyCode,
      currencyDecimals: fare?.currencyDecimals ?? ride.currencyDecimals,
    );
  }
}
