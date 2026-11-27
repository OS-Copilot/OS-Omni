import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../app/app_state.dart';
import '../../../features/map/domain/map_adapter.dart';
import '../../../shared/layout/adaptive_layout.dart';
import '../../../shared/models/models.dart';
import '../../../shared/theme/app_theme.dart';
import '../../../shared/utils/ride_math.dart';
import '../../../shared/widgets/app_widgets.dart';

class DriverHomeScreen extends StatefulWidget {
  const DriverHomeScreen({super.key});

  @override
  State<DriverHomeScreen> createState() => _DriverHomeScreenState();
}

class _DriverHomeScreenState extends State<DriverHomeScreen> {
  final _license = TextEditingController();
  final _make = TextEditingController();
  final _model = TextEditingController();
  final _year = TextEditingController();
  final _plate = TextEditingController();
  final _color = TextEditingController();
  final _documentIdentifier = TextEditingController(text: 'DOC-2026-0001');
  final _documentExpiry = TextEditingController(text: '2027-12-31');
  final _payoutAmount = TextEditingController();
  final _payoutNote = TextEditingController(text: 'Weekly payout request');
  final _supportMessage = TextEditingController(
    text: 'I need help with this trip.',
  );
  final _map = const ServiceMapAdapter();
  bool _seeded = false;
  int _section = 0;

  @override
  void dispose() {
    _license.dispose();
    _make.dispose();
    _model.dispose();
    _year.dispose();
    _plate.dispose();
    _color.dispose();
    _documentIdentifier.dispose();
    _documentExpiry.dispose();
    _payoutAmount.dispose();
    _payoutNote.dispose();
    _supportMessage.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_seeded) return;
    final profile = context.read<AppState>().driverProfile;
    if (profile != null) {
      _license.text = profile.licenseNumber;
      _make.text = profile.vehicleMake;
      _model.text = profile.vehicleModel;
      _year.text = profile.vehicleYear;
      _plate.text = profile.licensePlate;
      _color.text = profile.vehicleColor;
      _seeded = true;
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final profile = state.driverProfile;
    final active = state.activeRide;
    final driverLocation = _driverLocation(profile);
    final primary = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _DriverHeader(
          section: _section,
          onChanged: (value) => setState(() => _section = value),
        ),
        const SizedBox(height: 16),
        if (state.errorMessage != null) ...[
          ErrorBanner(state.errorMessage!),
          const SizedBox(height: 16),
        ],
        switch (_section) {
          0 => _workSection(state, profile, active),
          1 => _moneySection(state, profile),
          2 => _accountSection(state, profile, active),
          _ => _supportSection(state, active),
        },
      ],
    );
    final secondary = _DriverSidebar(
      profile: profile,
      active: active,
      map: _map,
      driverLocation: driverLocation,
      serviceCenter: state.selectedCity?.centerLocation,
    );
    return ScreenContainer(
      title: 'Driver Workspace',
      actions: [
        IconButton(
          tooltip: 'Refresh',
          onPressed: state.refreshDriver,
          icon: const Icon(Icons.refresh),
        ),
        IconButton(
          tooltip: 'Logout',
          onPressed: state.logout,
          icon: const Icon(Icons.logout),
        ),
      ],
      child: RefreshIndicator(
        onRefresh: state.refreshDriver,
        child: ResponsiveTwoColumnLayout(
          primary: primary,
          secondary: secondary,
        ),
      ),
    );
  }

  Widget _workSection(
    AppState state,
    DriverProfile? profile,
    Ride? active,
  ) {
    final driverLocation = _driverLocation(profile);
    final hasAcceptedTrip = active != null && active.status != 'searching';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DriverWorkQueueCard(
          profile: profile,
          active: active,
          incomingCount: state.incomingRides.length,
          onGoOnline: () => state.setDriverStatus('online'),
          onGoOffline: () => state.setDriverStatus('offline'),
          onOpenRequests: () => setState(() => _section = 0),
          onOpenTrip: () => setState(() => _section = 0),
          onGenerate: state.generateIncomingRide,
        ),
        const SizedBox(height: 16),
        if (profile?.verificationStatus != 'approved')
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const EmptyState(
                  'Finish account setup before driving.',
                ),
                const SizedBox(height: 10),
                FilledButton.icon(
                  onPressed: () => setState(() => _section = 2),
                  icon: const Icon(Icons.manage_accounts),
                  label: const Text('Open account setup'),
                ),
              ],
            ),
          )
        else if (hasAcceptedTrip)
          DriverActiveTrip(
            ride: active,
            driverProfile: profile,
          )
        else ...[
          if (profile?.driverStatus == 'online') ...[
            IncomingRideList(
              rides: state.incomingRides,
              driverLocation: driverLocation,
              onGenerate: state.generateIncomingRide,
            ),
          ],
        ],
      ],
    );
  }

  Widget _accountSection(AppState state, DriverProfile? profile, Ride? active) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      'Availability',
                      style: Theme.of(context)
                          .textTheme
                          .headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w900),
                    ),
                  ),
                  RideStatusBadge(profile?.driverStatus ?? 'offline'),
                ],
              ),
              const SizedBox(height: 8),
              Text('Verification: ${profile?.verificationStatus ?? 'pending'}'),
              const SizedBox(height: 14),
              if (profile == null)
                const EmptyState('Driver profile missing.')
              else if (!profile.isComplete)
                const EmptyState(
                  'Complete your vehicle profile before admin review.',
                )
              else if (profile.verificationStatus != 'approved')
                const EmptyState(
                  'Verification pending. Admin must approve this driver before accepting rides.',
                ),
              FilledButton.icon(
                onPressed: profile?.verificationStatus == 'approved' &&
                        profile?.driverStatus != 'busy'
                    ? () => state.setDriverStatus(
                          profile?.driverStatus == 'online'
                              ? 'offline'
                              : 'online',
                        )
                    : null,
                icon: Icon(
                  profile?.driverStatus == 'online'
                      ? Icons.pause_circle
                      : Icons.play_circle,
                ),
                label: Text(
                  profile?.driverStatus == 'online'
                      ? 'Go offline'
                      : 'Go online',
                ),
              ),
              if (profile?.verificationStatus == 'approved') ...[
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: () => setState(() => _section = 0),
                  icon: const Icon(Icons.fact_check),
                  label: Text(
                    active != null && active.status != 'searching'
                        ? 'Continue active trip'
                        : state.incomingRides.isEmpty
                            ? 'Open requests'
                            : 'Open ${state.incomingRides.length} request${state.incomingRides.length == 1 ? '' : 's'}',
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 16),
        DriverOnboardingForm(
          controllers: [_license, _make, _model, _year, _plate, _color],
        ),
        const SizedBox(height: 16),
        DriverDocumentsCard(
          identifier: _documentIdentifier,
          expiresAt: _documentExpiry,
        ),
      ],
    );
  }

  Widget _moneySection(AppState state, DriverProfile? profile) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _earningsSection(state, profile),
        const SizedBox(height: 16),
        _payoutSection(state),
      ],
    );
  }

  LocationPoint? _driverLocation(DriverProfile? profile) {
    if (profile == null) return null;
    return LocationPoint(
      address: 'Driver current location',
      cityId: context.read<AppState>().selectedCity?.id ?? '',
      latitude: profile.currentLatitude,
      longitude: profile.currentLongitude,
    );
  }

  Widget _payoutSection(AppState state) {
    final currencySymbol = state.earnings['currencySymbol'] as String? ?? r'$';
    final currencyCode = state.earnings['currencyCode'] as String? ?? 'USD';
    final currencyDecimals =
        (state.earnings['currencyDecimals'] as num?)?.toInt() ?? 2;
    String money(Object? value) => formatMoney(
          (value as num?)?.toDouble() ?? 0,
          currencySymbol: currencySymbol,
          currencyCode: currencyCode,
          currencyDecimals: currencyDecimals,
        );
    if (_payoutAmount.text.isEmpty &&
        (state.earnings['available'] as num?) != null) {
      _payoutAmount.text =
          (state.earnings['available'] as num).toStringAsFixed(2);
    }
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Payouts', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              MetricCard(
                label: 'Available',
                value: money(state.earnings['available']),
                icon: Icons.savings,
              ),
              MetricCard(
                label: 'Pending',
                value: money(state.earnings['pendingPayout']),
                icon: Icons.hourglass_top,
              ),
              MetricCard(
                label: 'Withdrawn',
                value: money(state.earnings['withdrawn']),
                icon: Icons.account_balance,
              ),
            ],
          ),
          const SizedBox(height: 12),
          AppTextField(
            controller: _payoutAmount,
            label: 'Amount',
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 8),
          AppTextField(controller: _payoutNote, label: 'Note'),
          const SizedBox(height: 10),
          FilledButton.icon(
            onPressed: () {
              final amount = double.tryParse(_payoutAmount.text.trim()) ?? 0;
              state.requestDriverPayout(amount, _payoutNote.text);
            },
            icon: const Icon(Icons.payments),
            label: const Text('Request payout'),
          ),
          const SizedBox(height: 16),
          if (state.driverPayouts.isEmpty)
            const EmptyState('No payout requests yet.'),
          for (final payout in state.driverPayouts)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.account_balance_wallet),
              title: Text(
                formatMoney(
                  (payout['amount'] as num?)?.toDouble() ?? 0,
                  currencySymbol: payout['currencySymbol'] as String? ?? r'$',
                  currencyCode: payout['currencyCode'] as String? ?? 'USD',
                  currencyDecimals:
                      (payout['currencyDecimals'] as num?)?.toInt() ?? 2,
                ),
              ),
              subtitle: Text(
                '${payout['note'] ?? ''}${(payout['adminNote'] as String? ?? '').isEmpty ? '' : '\nAdmin: ${payout['adminNote']}'}',
              ),
              trailing: RideStatusBadge(payout['status'] as String? ?? ''),
            ),
        ],
      ),
    );
  }

  Widget _earningsSection(AppState state, DriverProfile? profile) {
    final currencySymbol = state.earnings['currencySymbol'] as String? ?? r'$';
    final currencyCode = state.earnings['currencyCode'] as String? ?? 'USD';
    final currencyDecimals =
        (state.earnings['currencyDecimals'] as num?)?.toInt() ?? 2;
    String money(Object? value) => formatMoney(
          (value as num?)?.toDouble() ?? 0,
          currencySymbol: currencySymbol,
          currencyCode: currencyCode,
          currencyDecimals: currencyDecimals,
        );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            MetricCard(
              label: 'Today',
              value: money(state.earnings['today']),
              icon: Icons.today,
            ),
            MetricCard(
              label: 'Total',
              value: money(state.earnings['total']),
              icon: Icons.account_balance_wallet,
            ),
            MetricCard(
              label: 'Trips',
              value: state.earnings['completedTrips'] ?? 0,
              icon: Icons.route,
            ),
            MetricCard(
              label: 'Rating',
              value: profile?.averageRating.toStringAsFixed(1) ?? '5.0',
              icon: Icons.star,
            ),
          ],
        ),
        const SizedBox(height: 16),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Trip earnings',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 10),
              if (state.rideHistory.isEmpty)
                const EmptyState('No completed driver trips yet.'),
              for (final ride in state.rideHistory) ...[
                TripCard(ride: ride),
                const SizedBox(height: 8),
                DriverHistoryActions(ride: ride),
                const SizedBox(height: 10),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _supportSection(AppState state, Ride? active) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Driver safety and support',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          const Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _DriverSafetyChip(
                icon: Icons.verified,
                label: 'Rider verification',
              ),
              _DriverSafetyChip(icon: Icons.report, label: 'Report rider'),
              _DriverSafetyChip(
                icon: Icons.support_agent,
                label: 'Operations support',
              ),
            ],
          ),
          const SizedBox(height: 16),
          AppTextField(
            controller: _supportMessage,
            label: 'Message',
            minLines: 3,
            maxLines: 5,
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () => state.createSupportTicket(
              _supportMessage.text,
              category: 'rider issue',
              rideId: active?.id ?? '',
            ),
            icon: const Icon(Icons.support_agent),
            label: const Text('Create support ticket'),
          ),
          const SizedBox(height: 16),
          if (state.supportTickets.isEmpty)
            const EmptyState('No driver support tickets yet.'),
          for (final ticket in state.supportTickets)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.confirmation_number),
              title: Text('${ticket.category} - ${ticket.status}'),
              subtitle: Text(
                ticket.replies.isEmpty
                    ? ticket.message
                    : '${ticket.message}\n${ticket.replies.length} replies',
              ),
              trailing: IconButton(
                tooltip: 'Reply to ticket',
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => DriverSupportReplyDialog(ticket: ticket),
                ),
                icon: const Icon(Icons.reply),
              ),
            ),
        ],
      ),
    );
  }
}

class _DriverHeader extends StatelessWidget {
  const _DriverHeader({required this.section, required this.onChanged});

  final int section;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<int>(
      segments: const [
        ButtonSegment(
          value: 0,
          icon: Icon(Icons.local_taxi),
          label: Text('Work'),
        ),
        ButtonSegment(
          value: 1,
          icon: Icon(Icons.payments),
          label: Text('Money'),
        ),
        ButtonSegment(
          value: 2,
          icon: Icon(Icons.manage_accounts),
          label: Text('Account'),
        ),
        ButtonSegment(
          value: 3,
          icon: Icon(Icons.health_and_safety),
          label: Text('Support'),
        ),
      ],
      selected: {section},
      onSelectionChanged: (value) => onChanged(value.first),
    );
  }
}

class DriverOnboardingForm extends StatelessWidget {
  const DriverOnboardingForm({required this.controllers, super.key});

  final List<TextEditingController> controllers;

  @override
  Widget build(BuildContext context) {
    final labels = [
      'License number',
      'Vehicle make',
      'Vehicle model',
      'Vehicle year',
      'License plate',
      'Vehicle color',
    ];
    final keys = [
      'licenseNumber',
      'vehicleMake',
      'vehicleModel',
      'vehicleYear',
      'licensePlate',
      'vehicleColor',
    ];
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Driver onboarding',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          for (var i = 0; i < labels.length; i++) ...[
            AppTextField(
              controller: controllers[i],
              label: labels[i],
              keyboardType:
                  labels[i] == 'Vehicle year' ? TextInputType.number : null,
            ),
            const SizedBox(height: 8),
          ],
          FilledButton.tonalIcon(
            onPressed: () {
              final payload = <String, dynamic>{};
              for (var i = 0; i < keys.length; i++) {
                payload[keys[i]] = controllers[i].text.trim();
              }
              context.read<AppState>().saveDriverProfile(payload);
            },
            icon: const Icon(Icons.save),
            label: const Text('Save profile for review'),
          ),
        ],
      ),
    );
  }
}

class DriverDocumentsCard extends StatefulWidget {
  const DriverDocumentsCard({
    required this.identifier,
    required this.expiresAt,
    super.key,
  });

  final TextEditingController identifier;
  final TextEditingController expiresAt;

  @override
  State<DriverDocumentsCard> createState() => _DriverDocumentsCardState();
}

class _DriverDocumentsCardState extends State<DriverDocumentsCard> {
  String _type = 'license';

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final summary = state.driverDocumentSummary;
    const types = {
      'license': 'Driver license',
      'insurance': 'Insurance',
      'vehicle_inspection': 'Vehicle inspection',
      'vehicle_registration': 'Vehicle registration',
      'background_check': 'Background check',
    };
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Driver documents',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              RideStatusBadge(summary['status'] as String? ?? 'missing'),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '${summary['submitted'] ?? 0}/${summary['required'] ?? 3} required submitted - ${summary['approved'] ?? 0} approved',
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _type,
            decoration: const InputDecoration(
              labelText: 'Document type',
              border: OutlineInputBorder(),
            ),
            items: types.entries
                .map(
                  (entry) => DropdownMenuItem(
                    value: entry.key,
                    child: Text(entry.value),
                  ),
                )
                .toList(),
            onChanged: (value) => setState(() => _type = value ?? _type),
          ),
          const SizedBox(height: 8),
          AppTextField(
            controller: widget.identifier,
            label: 'Document ID',
          ),
          const SizedBox(height: 8),
          AppTextField(
            controller: widget.expiresAt,
            label: 'Expires at',
          ),
          const SizedBox(height: 10),
          FilledButton.tonalIcon(
            onPressed: () => state.submitDriverDocument(
              type: _type,
              identifier: widget.identifier.text,
              label: types[_type] ?? _type,
              expiresAt: widget.expiresAt.text,
            ),
            icon: const Icon(Icons.upload_file),
            label: const Text('Submit document'),
          ),
          const SizedBox(height: 12),
          if (state.driverDocuments.isEmpty)
            const EmptyState('No documents submitted yet.'),
          for (final document in state.driverDocuments)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.description),
              title: Text(document['label'] as String? ?? ''),
              subtitle: Text(
                '${document['identifier'] ?? ''}${(document['reviewNote'] as String? ?? '').isEmpty ? '' : '\nReview: ${document['reviewNote']}'}',
              ),
              trailing: RideStatusBadge(document['status'] as String? ?? ''),
            ),
        ],
      ),
    );
  }
}

class DriverWorkQueueCard extends StatelessWidget {
  const DriverWorkQueueCard({
    required this.profile,
    required this.active,
    required this.incomingCount,
    required this.onGoOnline,
    required this.onGoOffline,
    required this.onOpenRequests,
    required this.onOpenTrip,
    required this.onGenerate,
    super.key,
  });

  final DriverProfile? profile;
  final Ride? active;
  final int incomingCount;
  final VoidCallback onGoOnline;
  final VoidCallback onGoOffline;
  final VoidCallback onOpenRequests;
  final VoidCallback onOpenTrip;
  final VoidCallback onGenerate;

  @override
  Widget build(BuildContext context) {
    final approved = profile?.verificationStatus == 'approved';
    final online = profile?.driverStatus == 'online';
    final busy = profile?.driverStatus == 'busy' || active != null;
    final title = active != null
        ? 'Active trip in progress'
        : incomingCount > 0
            ? '$incomingCount incoming request${incomingCount == 1 ? '' : 's'}'
            : online
                ? 'Online and waiting for requests'
                : approved
                    ? 'Ready to go online'
                    : 'Complete approval before driving';
    final subtitle = active != null
        ? _driverStageMessage(active!.status)
        : incomingCount > 0
            ? 'Review pickup, destination, rider, fare, then accept or reject.'
            : online
                ? 'A benchmark request will arrive automatically in 15-30 seconds.'
                : approved
                    ? 'Go online to enter the request queue.'
                    : 'Submit profile and documents for admin review.';

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CircleAvatar(
                backgroundColor: AppColors.accent.withValues(alpha: 0.12),
                child: Icon(
                  active != null
                      ? Icons.route
                      : incomingCount > 0
                          ? Icons.fact_check
                          : online
                              ? Icons.radar
                              : Icons.power_settings_new,
                  color: AppColors.accent,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: Theme.of(context)
                          .textTheme
                          .titleLarge
                          ?.copyWith(fontWeight: FontWeight.w900),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        color: AppColors.muted,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
              RideStatusBadge(profile?.driverStatus ?? 'offline'),
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              if (active != null)
                FilledButton.icon(
                  onPressed: onOpenTrip,
                  icon: const Icon(Icons.navigation),
                  label: const Text('Open trip'),
                )
              else if (incomingCount > 0)
                FilledButton.icon(
                  onPressed: onOpenRequests,
                  icon: const Icon(Icons.fact_check),
                  label: const Text('Review requests'),
                )
              else if (approved && !online)
                FilledButton.icon(
                  onPressed: onGoOnline,
                  icon: const Icon(Icons.play_circle),
                  label: const Text('Go online'),
                )
              else if (approved && online)
                FilledButton.icon(
                  onPressed: onGenerate,
                  icon: const Icon(Icons.add_road),
                  label: const Text('Generate request now'),
                ),
              if (approved && online && !busy)
                OutlinedButton.icon(
                  onPressed: onGoOffline,
                  icon: const Icon(Icons.pause_circle),
                  label: const Text('Go offline'),
                ),
              if (approved && active == null)
                OutlinedButton.icon(
                  onPressed: onOpenRequests,
                  icon: const Icon(Icons.inbox),
                  label: const Text('Open queue'),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class IncomingRideList extends StatelessWidget {
  const IncomingRideList({
    required this.rides,
    this.driverLocation,
    this.onGenerate,
    super.key,
  });

  final List<Ride> rides;
  final LocationPoint? driverLocation;
  final VoidCallback? onGenerate;

  @override
  Widget build(BuildContext context) {
    final state = context.read<AppState>();
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Available ride requests',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          if (rides.isEmpty) ...[
            const EmptyState(
              'No incoming requests. Create a sample request or wait for a rider.',
            ),
            if (onGenerate != null) ...[
              const SizedBox(height: 10),
              FilledButton.icon(
                onPressed: onGenerate,
                icon: const Icon(Icons.add_road),
                label: const Text('Create sample request'),
              ),
            ],
          ],
          for (final ride in rides)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  DriverRouteSummary(ride: ride, stage: 'request'),
                  const SizedBox(height: 10),
                  DriverRequestSnapshot(
                    ride: ride,
                    driverLocation: driverLocation,
                  ),
                  const SizedBox(height: 10),
                  TripCard(ride: ride),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: () => state.acceptRide(ride.id),
                          icon: const Icon(Icons.check),
                          label: const Text('Accept trip'),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: () => state.rejectRide(ride.id),
                          icon: const Icon(Icons.close),
                          label: const Text('Reject'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class CurrentDriverTripCard extends StatelessWidget {
  const CurrentDriverTripCard({
    required this.ride,
    required this.map,
    required this.onContinue,
    this.driverLocation,
    this.serviceCenter,
    super.key,
  });

  final Ride ride;
  final MapAdapter map;
  final LocationPoint? driverLocation;
  final LocationPoint? serviceCenter;
  final VoidCallback onContinue;

  @override
  Widget build(BuildContext context) {
    final next = switch (ride.status) {
      'accepted' => ('driver_arriving', 'Start driving to pickup'),
      'driver_arriving' => ('arrived', 'Mark arrived'),
      'in_progress' => ('completed', 'Complete trip'),
      _ => null,
    };
    final arrivalDistanceKm = _driverDistanceToPickupKm(
      ride: ride,
      driverProfile: null,
      driverLocation: driverLocation,
    );
    final arrivalWaitSeconds = _secondsUntilDriverArrival(ride);
    final completionDistanceKm = _driverDistanceToDestinationKm(
      ride: ride,
      driverProfile: null,
      driverLocation: driverLocation,
    );
    final completionWaitSeconds = _secondsUntilTripCompletion(ride);
    final nextEnabled = next?.$1 != 'arrived' ||
        (arrivalDistanceKm <= 0.05 && arrivalWaitSeconds <= 0);
    final actionEnabled = next?.$1 == 'completed'
        ? completionDistanceKm <= 0.05 && completionWaitSeconds <= 0
        : nextEnabled;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Current accepted trip',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 8),
        map.buildMap(
          currentLocation: driverLocation,
          driver: driverLocation,
          serviceCenter: serviceCenter,
          ride: ride,
          compact: true,
          focusLocation: _focusForRide(ride),
        ),
        const SizedBox(height: 10),
        DriverRouteSummary(ride: ride, stage: ride.status),
        const SizedBox(height: 10),
        TripCard(ride: ride),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: onContinue,
                icon: const Icon(Icons.route),
                label: const Text('Open trip controls'),
              ),
            ),
            if (next != null) ...[
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: actionEnabled
                      ? () => context
                          .read<AppState>()
                          .updateDriverRideStatus(ride.id, next.$1)
                      : null,
                  icon: const Icon(Icons.arrow_forward),
                  label: Text(next.$2),
                ),
              ),
            ],
            if (ride.status == 'arrived') ...[
              const SizedBox(width: 10),
              const Expanded(
                child: _DriverWaitingForRiderButton(),
              ),
            ],
          ],
        ),
      ],
    );
  }
}

class DriverRequestSnapshot extends StatelessWidget {
  const DriverRequestSnapshot({
    required this.ride,
    this.driverLocation,
    super.key,
  });

  final Ride ride;
  final LocationPoint? driverLocation;

  @override
  Widget build(BuildContext context) {
    final pickupDistance = driverLocation == null
        ? 0.0
        : calculateHaversineDistance(
            startLatitude: driverLocation!.latitude,
            startLongitude: driverLocation!.longitude,
            endLatitude: ride.pickupLatitude,
            endLongitude: ride.pickupLongitude,
          );
    final pickupMinutes = pickupDistance <= 0
        ? 1
        : (pickupDistance / 22 * 60).clamp(1, 60).ceil();
    final earnings = (ride.estimatedFare * 0.82);
    final fare = ride.fareBreakdown;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.accent.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.accent.withValues(alpha: 0.16)),
      ),
      child: Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          _DriverFactPill(
            icon: Icons.person,
            label: ride.rider?.name ?? 'Rider',
          ),
          _DriverFactPill(
            icon: Icons.near_me,
            label: '${pickupDistance.toStringAsFixed(1)} km pickup',
          ),
          _DriverFactPill(
            icon: Icons.timer,
            label: '$pickupMinutes min to pickup',
          ),
          if (ride.scheduledFor.isNotEmpty)
            _DriverFactPill(
              icon: Icons.event,
              label: 'Pickup ${_formatDriverPickupTime(ride.scheduledFor)}',
            ),
          _DriverFactPill(
            icon: Icons.route,
            label: '${ride.estimatedDistance.toStringAsFixed(1)} km trip',
          ),
          if (fare != null && fare.pickupTimeAdjustment != 0)
            _DriverFactPill(
              icon: Icons.trending_up,
              label:
                  '${fare.pickupTimeLabel} ${formatMoney(fare.pickupTimeAdjustment, currencySymbol: fare.currencySymbol, currencyCode: fare.currencyCode, currencyDecimals: fare.currencyDecimals)}',
            ),
          _DriverFactPill(
            icon: Icons.payments,
            label:
                '${formatMoney(earnings, currencySymbol: ride.currencySymbol, currencyCode: ride.currencyCode, currencyDecimals: ride.currencyDecimals)} est earnings',
          ),
        ],
      ),
    );
  }
}

String _formatDriverPickupTime(String value) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return value;
  String two(int number) => number.toString().padLeft(2, '0');
  return '${two(parsed.hour)}:${two(parsed.minute)}';
}

int _secondsUntilDriverArrival(Ride ride) {
  final arriveAt = ride.automationFlow['arriveAt'] as String?;
  final parsed = arriveAt == null ? null : DateTime.tryParse(arriveAt);
  if (parsed == null) return 0;
  final remaining = parsed.difference(DateTime.now()).inSeconds;
  return remaining > 0 ? remaining : 0;
}

int _secondsUntilTripCompletion(Ride ride) {
  final completeAt = ride.automationFlow['completeAt'] as String?;
  final parsed = completeAt == null ? null : DateTime.tryParse(completeAt);
  if (parsed == null) return 0;
  final remaining = parsed.difference(DateTime.now()).inSeconds;
  return remaining > 0 ? remaining : 0;
}

double _driverDistanceToPickupKm({
  required Ride ride,
  DriverProfile? driverProfile,
  LocationPoint? driverLocation,
}) {
  final serverDistance = ride.driverDistanceToPickupKm;
  if (serverDistance != null) return serverDistance;
  if (driverProfile != null) {
    return calculateHaversineDistance(
      startLatitude: driverProfile.currentLatitude,
      startLongitude: driverProfile.currentLongitude,
      endLatitude: ride.pickupLatitude,
      endLongitude: ride.pickupLongitude,
    );
  }
  if (driverLocation != null) {
    return calculateHaversineDistance(
      startLatitude: driverLocation.latitude,
      startLongitude: driverLocation.longitude,
      endLatitude: ride.pickupLatitude,
      endLongitude: ride.pickupLongitude,
    );
  }
  return double.infinity;
}

double _driverDistanceToDestinationKm({
  required Ride ride,
  DriverProfile? driverProfile,
  LocationPoint? driverLocation,
}) {
  final serverDistance = ride.driverDistanceToDestinationKm;
  if (serverDistance != null) return serverDistance;
  if (driverProfile != null) {
    return calculateHaversineDistance(
      startLatitude: driverProfile.currentLatitude,
      startLongitude: driverProfile.currentLongitude,
      endLatitude: ride.destinationLatitude,
      endLongitude: ride.destinationLongitude,
    );
  }
  if (driverLocation != null) {
    return calculateHaversineDistance(
      startLatitude: driverLocation.latitude,
      startLongitude: driverLocation.longitude,
      endLatitude: ride.destinationLatitude,
      endLongitude: ride.destinationLongitude,
    );
  }
  return double.infinity;
}

class _DriverFactPill extends StatelessWidget {
  const _DriverFactPill({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: Icon(icon, size: 17, color: AppColors.accent),
      label: Text(label),
      backgroundColor: Colors.white,
      side: BorderSide(color: AppColors.accent.withValues(alpha: 0.18)),
    );
  }
}

LocationPoint _focusForRide(Ride ride) {
  final headingToDestination =
      ride.status == 'in_progress' || ride.status == 'completed';
  return headingToDestination
      ? LocationPoint(
          address: ride.destinationAddress,
          latitude: ride.destinationLatitude,
          longitude: ride.destinationLongitude,
        )
      : LocationPoint(
          address: ride.pickupAddress,
          latitude: ride.pickupLatitude,
          longitude: ride.pickupLongitude,
        );
}

class DriverRouteSummary extends StatelessWidget {
  const DriverRouteSummary(
      {required this.ride, required this.stage, super.key});

  final Ride ride;
  final String stage;

  @override
  Widget build(BuildContext context) {
    final headingToDestination = stage == 'in_progress' || stage == 'completed';
    final title = switch (stage) {
      'request' => 'Pickup preview',
      'accepted' => 'Ready to pickup',
      'driver_arriving' => 'Driving to pickup',
      'arrived' => 'Waiting at pickup',
      'in_progress' => 'Navigate to destination',
      'completed' => 'Trip completed',
      _ => 'Navigate to pickup',
    };
    final nextStep = switch (stage) {
      'request' => 'Review the route, fare, and pickup before accepting.',
      'accepted' => 'Next: start driving toward the pickup point.',
      'driver_arriving' =>
        'Next: mark arrived when you reach the pickup point.',
      'arrived' => 'Next: wait for the rider, then start the trip.',
      'in_progress' =>
        'Next: follow the route and complete the trip at destination.',
      'completed' => 'Ride is complete and earnings are ready.',
      _ => 'Follow the route shown above.',
    };
    final target =
        headingToDestination ? ride.destinationAddress : ride.pickupAddress;
    final distance =
        (ride.finalDistance ?? ride.estimatedDistance).toStringAsFixed(1);
    final minutes = ride.finalDuration ?? ride.estimatedDuration;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF6F8FC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            headingToDestination ? Icons.flag : Icons.location_pin,
            color: AppColors.accent,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 4),
                Text(target),
                const SizedBox(height: 6),
                Text('$distance km - about $minutes min'),
                const SizedBox(height: 6),
                Text(
                  nextStep,
                  style: const TextStyle(
                    color: Color(0xFF64748B),
                    fontWeight: FontWeight.w700,
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

class DriverActiveTrip extends StatelessWidget {
  const DriverActiveTrip({
    required this.ride,
    required this.driverProfile,
    super.key,
  });

  final Ride? ride;
  final DriverProfile? driverProfile;

  @override
  Widget build(BuildContext context) {
    final next = switch (ride?.status) {
      'accepted' => ('driver_arriving', 'Start driving to pickup'),
      'driver_arriving' => ('arrived', 'Mark arrived'),
      'in_progress' => ('completed', 'Complete trip'),
      _ => null,
    };
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Active trip controls',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          if (ride == null)
            const EmptyState(
              'No active trip. Accept an incoming request to start.',
            )
          else ...[
            DriverRouteSummary(ride: ride!, stage: ride!.status),
            const SizedBox(height: 10),
            TripCard(ride: ride!),
            const SizedBox(height: 10),
            DriverRiderInfoCard(ride: ride!),
            const SizedBox(height: 8),
            RideTimeline(status: ride!.status, entries: ride!.timeline),
            const SizedBox(height: 10),
            DriverTripActionPanel(
              ride: ride!,
              next: next,
              driverProfile: driverProfile,
            ),
            if (ride!.status == 'completed') ...[
              const SizedBox(height: 10),
              ReceiptCard(ride: ride!),
            ],
          ],
        ],
      ),
    );
  }
}

class DriverHistoryActions extends StatelessWidget {
  const DriverHistoryActions({required this.ride, super.key});

  final Ride ride;

  @override
  Widget build(BuildContext context) {
    final completed = ride.status == 'completed';
    final cancelled = ride.status == 'cancelled';
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        RideStatusBadge(ride.status),
        if (completed)
          OutlinedButton.icon(
            onPressed: () => showDialog<void>(
              context: context,
              builder: (_) => AlertDialog(
                title: const Text('Trip receipt'),
                content: SizedBox(width: 420, child: ReceiptCard(ride: ride)),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Close'),
                  ),
                ],
              ),
            ),
            icon: const Icon(Icons.receipt_long),
            label: const Text('Receipt'),
          ),
        if (completed)
          OutlinedButton.icon(
            onPressed: () => showDialog<void>(
              context: context,
              builder: (_) => DriverRatingDialog(rideId: ride.id),
            ),
            icon: const Icon(Icons.star),
            label: const Text('Rate rider'),
          ),
        if (cancelled)
          const _DriverFactPill(
            icon: Icons.info_outline,
            label: 'No earnings captured',
          ),
      ],
    );
  }
}

class DriverRiderInfoCard extends StatelessWidget {
  const DriverRiderInfoCard({required this.ride, super.key});

  final Ride ride;

  @override
  Widget build(BuildContext context) {
    final rider = ride.rider;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              CircleAvatar(
                backgroundColor: AppColors.ink,
                child: Text(
                  (rider?.name.isNotEmpty == true ? rider!.name[0] : 'R')
                      .toUpperCase(),
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      rider?.name ?? 'Rider',
                      style: const TextStyle(
                        fontWeight: FontWeight.w900,
                        fontSize: 18,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Pickup: ${ride.pickupAddress}',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: AppColors.muted),
                    ),
                  ],
                ),
              ),
              RideStatusBadge(ride.status),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: () => _showDriverCallSheet(
                  context,
                  rider?.name ?? 'rider',
                  rider?.phone ?? '',
                ),
                icon: const Icon(Icons.phone),
                label: Text(
                  rider?.phone.isNotEmpty == true
                      ? 'Call ${_maskPhone(rider!.phone)}'
                      : 'Call rider',
                ),
              ),
              OutlinedButton.icon(
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => DriverRideMessageDialog(ride: ride),
                ),
                icon: const Icon(Icons.chat_bubble_outline),
                label: const Text('Message'),
              ),
              OutlinedButton.icon(
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => DriverSafetyDialog(ride: ride),
                ),
                icon: const Icon(Icons.shield_outlined),
                label: const Text('Safety'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class DriverTripActionPanel extends StatelessWidget {
  const DriverTripActionPanel({
    required this.ride,
    required this.next,
    required this.driverProfile,
    super.key,
  });

  final Ride ride;
  final (String, String)? next;
  final DriverProfile? driverProfile;

  @override
  Widget build(BuildContext context) {
    final canCancel = ['accepted', 'driver_arriving', 'arrived'].contains(
      ride.status,
    );
    final completed = ride.status == 'completed';
    final arrivalDistanceKm = _driverDistanceToPickupKm(
      ride: ride,
      driverProfile: driverProfile,
    );
    final arrivalWaitSeconds = _secondsUntilDriverArrival(ride);
    final completionDistanceKm = _driverDistanceToDestinationKm(
      ride: ride,
      driverProfile: driverProfile,
    );
    final completionWaitSeconds = _secondsUntilTripCompletion(ride);
    final blockedArrival = next?.$1 == 'arrived' &&
        (arrivalDistanceKm > 0.05 || arrivalWaitSeconds > 0);
    final blockedCompletion = next?.$1 == 'completed' &&
        (completionDistanceKm > 0.05 || completionWaitSeconds > 0);
    final arrivalBlockMessage = arrivalWaitSeconds > 0
        ? 'Driver is still en route. Mark arrived in about ${arrivalWaitSeconds}s.'
        : 'Move within 50 m of pickup before marking arrived. Current distance: ${arrivalDistanceKm.toStringAsFixed(1)} km.';
    final completionBlockMessage = completionWaitSeconds > 0
        ? 'Trip is still in progress. Complete it in about ${completionWaitSeconds}s.'
        : 'Move within 50 m of destination before completing the trip. Current distance: ${completionDistanceKm.toStringAsFixed(1)} km.';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (next != null)
          FilledButton.icon(
            onPressed: blockedArrival || blockedCompletion
                ? null
                : () => context
                    .read<AppState>()
                    .updateDriverRideStatus(ride.id, next!.$1),
            icon: const Icon(Icons.arrow_forward),
            label: Text(next!.$2),
          ),
        if (blockedArrival) ...[
          const SizedBox(height: 8),
          Text(
            arrivalBlockMessage,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppColors.muted,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
        if (blockedCompletion) ...[
          const SizedBox(height: 8),
          Text(
            completionBlockMessage,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppColors.muted,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
        if (ride.status == 'arrived') ...[
          const SizedBox(height: 8),
          const _DriverWaitingForRiderButton(),
          const SizedBox(height: 8),
          Text(
            'The rider must confirm pickup before this trip can start.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppColors.muted,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            OutlinedButton.icon(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (_) => DriverRideMessageDialog(ride: ride),
              ),
              icon: const Icon(Icons.message),
              label: const Text('Message rider'),
            ),
            OutlinedButton.icon(
              onPressed: () => context.read<AppState>().createSupportTicket(
                    'Driver needs operations support for ride ${ride.id}.',
                    category: 'rider issue',
                    rideId: ride.id,
                  ),
              icon: const Icon(Icons.support_agent),
              label: const Text('Contact support'),
            ),
            if (canCancel)
              OutlinedButton.icon(
                onPressed: () => _confirmDriverCancel(context, ride),
                icon: const Icon(Icons.cancel),
                label: const Text('Cancel trip'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.danger,
                  side: const BorderSide(color: AppColors.danger),
                ),
              ),
            if (completed)
              FilledButton.tonalIcon(
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => DriverRatingDialog(rideId: ride.id),
                ),
                icon: const Icon(Icons.star),
                label: const Text('Rate rider'),
              ),
          ],
        ),
      ],
    );
  }

  void _confirmDriverCancel(BuildContext context, Ride ride) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Cancel trip'),
        content: const Text(
          'This will cancel the assigned ride and notify operations.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Keep trip'),
          ),
          FilledButton.icon(
            onPressed: () {
              context.read<AppState>().cancelRide(
                    ride.id,
                    reason: 'Cancelled by driver',
                  );
              Navigator.pop(context);
            },
            icon: const Icon(Icons.cancel),
            label: const Text('Cancel trip'),
          ),
        ],
      ),
    );
  }
}

class _DriverWaitingForRiderButton extends StatelessWidget {
  const _DriverWaitingForRiderButton();

  @override
  Widget build(BuildContext context) {
    return FilledButton.icon(
      onPressed: null,
      icon: const Icon(Icons.hourglass_top),
      label: const Text('Waiting for rider'),
    );
  }
}

class DriverSafetyDialog extends StatelessWidget {
  const DriverSafetyDialog({required this.ride, super.key});

  final Ride ride;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Driver safety'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SafetyLine(
            icon: Icons.person_pin_circle,
            message: 'Verify the rider at ${ride.pickupAddress}.',
          ),
          const SizedBox(height: 8),
          const _SafetyLine(
            icon: Icons.lock,
            message: 'Keep communication inside opendriver messages.',
          ),
          const SizedBox(height: 8),
          const _SafetyLine(
            icon: Icons.report,
            message:
                'Use support for no-show, unsafe behavior, or route issues.',
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
        FilledButton.icon(
          onPressed: () {
            context.read<AppState>().createSupportTicket(
                  'Driver safety report for ride ${ride.id}.',
                  category: 'safety concern',
                  rideId: ride.id,
                );
            Navigator.pop(context);
          },
          icon: const Icon(Icons.report),
          label: const Text('Report issue'),
        ),
      ],
    );
  }
}

class _SafetyLine extends StatelessWidget {
  const _SafetyLine({required this.icon, required this.message});

  final IconData icon;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 20, color: AppColors.accent),
        const SizedBox(width: 8),
        Expanded(child: Text(message)),
      ],
    );
  }
}

class DriverRatingDialog extends StatefulWidget {
  const DriverRatingDialog({required this.rideId, super.key});

  final String rideId;

  @override
  State<DriverRatingDialog> createState() => _DriverRatingDialogState();
}

class _DriverRatingDialogState extends State<DriverRatingDialog> {
  int _score = 5;
  final _comment = TextEditingController();

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Rate rider'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          StarRatingInput(
            value: _score,
            label: 'Rider rating',
            onChanged: (value) => setState(() => _score = value),
          ),
          const SizedBox(height: 12),
          AppTextField(
            controller: _comment,
            label: 'Comment',
            minLines: 2,
            maxLines: 4,
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
        FilledButton.icon(
          onPressed: () {
            context.read<AppState>().rateRide(
                  widget.rideId,
                  _score,
                  _comment.text,
                );
            Navigator.pop(context);
          },
          icon: const Icon(Icons.star),
          label: const Text('Submit'),
        ),
      ],
    );
  }
}

String _driverStageMessage(String status) {
  return switch (status) {
    'accepted' => 'Start navigation toward pickup when ready.',
    'driver_arriving' => 'Drive to pickup and mark arrived at the pin.',
    'arrived' => 'Wait for the rider, message if needed, then start trip.',
    'in_progress' => 'Follow the destination route and complete the trip.',
    'completed' => 'Trip completed. Receipt and earnings are available.',
    'cancelled' => 'Trip cancelled.',
    _ => 'Review the trip details and continue the workflow.',
  };
}

String _maskPhone(String phone) {
  final digits = phone.replaceAll(RegExp(r'\D'), '');
  if (digits.length < 4) return phone.isEmpty ? 'rider' : phone;
  return '***-${digits.substring(digits.length - 4)}';
}

void _showDriverCallSheet(
    BuildContext context, String riderName, String phone) {
  showDialog<void>(
    context: context,
    builder: (_) => AlertDialog(
      title: Text('Call $riderName'),
      content: Text(
        'Call started through opendriver. Contact: ${phone.isEmpty ? 'masked rider line' : phone}.',
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

class _DriverSidebar extends StatelessWidget {
  const _DriverSidebar({
    required this.profile,
    required this.active,
    required this.map,
    this.driverLocation,
    this.serviceCenter,
  });

  final DriverProfile? profile;
  final Ride? active;
  final MapAdapter map;
  final LocationPoint? driverLocation;
  final LocationPoint? serviceCenter;

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final mapRide = active ??
        (state.incomingRides.isEmpty ? null : state.incomingRides.first);
    final navigationMode =
        ['driver_arriving', 'in_progress'].contains(mapRide?.status);
    final focusLocation = navigationMode
        ? driverLocation
        : mapRide == null
            ? driverLocation
            : _focusForRide(mapRide);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Map', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 10),
              map.buildMap(
                currentLocation: driverLocation,
                driver: driverLocation,
                serviceCenter: serviceCenter,
                ride: mapRide,
                compact: true,
                focusLocation: focusLocation,
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Vehicle', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              if (profile == null)
                const EmptyState('No profile yet.')
              else ...[
                Text(
                  '${profile!.vehicleColor} ${profile!.vehicleMake} ${profile!.vehicleModel}',
                  style: const TextStyle(fontWeight: FontWeight.w900),
                ),
                Text('Plate ${profile!.licensePlate}'),
                Text('License ${profile!.licenseNumber}'),
              ],
            ],
          ),
        ),
        const SizedBox(height: 16),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Notifications',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              if (state.notifications.isEmpty)
                const EmptyState('No notifications yet.'),
              for (final notification in state.notifications.take(5))
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    notification.read
                        ? Icons.notifications_none
                        : Icons.notifications_active,
                  ),
                  title: Text(notification.title),
                  subtitle: Text(notification.message),
                  trailing: notification.read
                      ? null
                      : IconButton(
                          tooltip: 'Mark read',
                          onPressed: () =>
                              state.markNotificationRead(notification.id),
                          icon: const Icon(Icons.done),
                        ),
                  onTap: notification.read
                      ? null
                      : () => state.markNotificationRead(notification.id),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class DriverRideMessageDialog extends StatefulWidget {
  const DriverRideMessageDialog({required this.ride, super.key});

  final Ride ride;

  @override
  State<DriverRideMessageDialog> createState() =>
      _DriverRideMessageDialogState();
}

class _DriverRideMessageDialogState extends State<DriverRideMessageDialog> {
  final _message = TextEditingController();

  @override
  void dispose() {
    _message.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final ride = state.activeRide?.id == widget.ride.id
        ? state.activeRide!
        : widget.ride;
    final messages = ride.messages;
    return AlertDialog(
      title: Text('Message ${ride.rider?.name ?? 'rider'}'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 260),
              child: messages.isEmpty
                  ? const EmptyState('No messages yet.')
                  : ListView.separated(
                      shrinkWrap: true,
                      itemCount: messages.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 8),
                      itemBuilder: (context, index) {
                        final item = messages[index];
                        final mine = item.senderRole == 'driver';
                        return Align(
                          alignment: mine
                              ? Alignment.centerRight
                              : Alignment.centerLeft,
                          child: Container(
                            constraints: const BoxConstraints(maxWidth: 310),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 9,
                            ),
                            decoration: BoxDecoration(
                              color: mine
                                  ? AppColors.accent
                                  : const Color(0xFFF1F4F8),
                              borderRadius: BorderRadius.circular(14),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  item.senderName,
                                  style: TextStyle(
                                    color:
                                        mine ? Colors.white70 : AppColors.muted,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  item.body,
                                  style: TextStyle(
                                    color: mine ? Colors.white : AppColors.ink,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final reply in [
                  'I am on my way.',
                  'I have arrived.',
                  'Please meet at the pickup pin.',
                ])
                  ActionChip(label: Text(reply), onPressed: () => _send(reply)),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _message,
              minLines: 1,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'Type a message',
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
        FilledButton.icon(
          onPressed: state.isLoading ? null : () => _send(_message.text),
          icon: const Icon(Icons.send),
          label: const Text('Send'),
        ),
      ],
    );
  }

  Future<void> _send(String body) async {
    final clean = body.trim();
    if (clean.isEmpty) return;
    await context.read<AppState>().sendRideMessage(widget.ride.id, clean);
    if (!mounted) return;
    _message.clear();
  }
}

class DriverSupportReplyDialog extends StatefulWidget {
  const DriverSupportReplyDialog({required this.ticket, super.key});

  final SupportTicket ticket;

  @override
  State<DriverSupportReplyDialog> createState() =>
      _DriverSupportReplyDialogState();
}

class _DriverSupportReplyDialogState extends State<DriverSupportReplyDialog> {
  final _message = TextEditingController(text: 'Following up on this ticket.');

  @override
  void dispose() {
    _message.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final matches =
        state.supportTickets.where((item) => item.id == widget.ticket.id);
    final ticket = matches.isEmpty ? widget.ticket : matches.first;
    return AlertDialog(
      title: Text('Ticket ${ticket.status}'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(ticket.message),
            const SizedBox(height: 12),
            if (ticket.replies.isEmpty)
              const EmptyState('No replies yet.')
            else
              for (final reply in ticket.replies)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    reply.role == 'admin' ? Icons.support_agent : Icons.person,
                  ),
                  title: Text(reply.userName),
                  subtitle: Text(reply.message),
                ),
            const SizedBox(height: 12),
            AppTextField(
              controller: _message,
              label: 'Reply',
              minLines: 2,
              maxLines: 4,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
        FilledButton.icon(
          onPressed: state.isLoading
              ? null
              : () async {
                  await context.read<AppState>().replyToSupportTicket(
                        ticket.id,
                        _message.text,
                      );
                  if (mounted) _message.clear();
                },
          icon: const Icon(Icons.send),
          label: const Text('Send reply'),
        ),
      ],
    );
  }
}

class _DriverSafetyChip extends StatelessWidget {
  const _DriverSafetyChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: Icon(icon, size: 18, color: AppColors.accent),
      label: Text(label),
      backgroundColor: AppColors.accent.withValues(alpha: 0.08),
      side: BorderSide.none,
    );
  }
}
