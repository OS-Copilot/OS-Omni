import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../app/app_state.dart';
import '../../../shared/layout/adaptive_layout.dart';
import '../../../shared/models/models.dart';
import '../../../shared/theme/app_theme.dart';
import '../../../shared/widgets/app_widgets.dart';

class AdminDashboardScreen extends StatefulWidget {
  const AdminDashboardScreen({super.key});

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  int _section = 0;

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final primary = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _AdminHeader(
          section: _section,
          onChanged: (value) => setState(() => _section = value),
        ),
        const SizedBox(height: 16),
        if (state.errorMessage != null) ...[
          ErrorBanner(state.errorMessage!),
          const SizedBox(height: 16),
        ],
        switch (_section) {
          0 => _overview(state),
          1 => _drivers(state),
          2 => _rides(state),
          3 => _payments(state),
          4 => _refunds(state),
          5 => _payouts(state),
          _ => _support(state),
        },
      ],
    );
    final secondary = _AdminSidebar(state: state);
    return ScreenContainer(
      title: 'Operations Workspace',
      actions: [
        IconButton(
          tooltip: 'Refresh',
          onPressed: state.refreshAdmin,
          icon: const Icon(Icons.refresh),
        ),
        IconButton(
          tooltip: 'Logout',
          onPressed: state.logout,
          icon: const Icon(Icons.logout),
        ),
      ],
      child: RefreshIndicator(
        onRefresh: state.refreshAdmin,
        child: ResponsiveTwoColumnLayout(
          primary: primary,
          secondary: secondary,
        ),
      ),
    );
  }

  Widget _overview(AppState state) {
    final metrics = state.adminMetrics;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            MetricCard(
              label: 'Users',
              value: metrics['totalUsers'],
              icon: Icons.group,
            ),
            MetricCard(
              label: 'Active drivers',
              value: metrics['activeDrivers'],
              icon: Icons.local_taxi,
            ),
            MetricCard(
              label: 'Pending drivers',
              value: metrics['pendingDrivers'],
              icon: Icons.verified_user,
            ),
            MetricCard(
              label: 'Total rides',
              value: metrics['totalRides'],
              icon: Icons.route,
            ),
            MetricCard(
              label: 'Completed',
              value: metrics['completedRides'],
              icon: Icons.check_circle,
            ),
            MetricCard(
              label: 'Cancelled',
              value: metrics['cancelledRides'],
              icon: Icons.cancel,
            ),
            MetricCard(
              label: 'Revenue',
              value: '\$${metrics['revenue'] ?? 0}',
              icon: Icons.payments,
            ),
            MetricCard(
              label: 'Open tickets',
              value: metrics['openSupportTickets'],
              icon: Icons.support_agent,
            ),
          ],
        ),
        const SizedBox(height: 16),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Users', style: Theme.of(context).textTheme.titleLarge),
              for (final user in state.adminUsers)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(_roleIcon(user.role)),
                  title: Text(user.name),
                  subtitle: Text('${user.email} - ${user.role.name}'),
                  trailing: user.isVerified
                      ? const Icon(Icons.verified, color: AppColors.accent)
                      : const Icon(Icons.pending),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _drivers(AppState state) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Driver management',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          for (final driver in state.adminDrivers)
            _DriverAdminTile(driver: driver),
        ],
      ),
    );
  }

  Widget _rides(AppState state) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Ride operations',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          if (state.adminRides.isEmpty) const EmptyState('No rides yet.'),
          for (final ride in state.adminRides) _RideAdminTile(ride: ride),
        ],
      ),
    );
  }

  Widget _support(AppState state) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Support tickets',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          if (state.supportTickets.isEmpty)
            const EmptyState('No support tickets.'),
          for (final ticket in state.supportTickets)
            _TicketAdminTile(ticket: ticket),
        ],
      ),
    );
  }

  Widget _payments(AppState state) {
    final totalAmount = state.adminPayments.fold<double>(
      0,
      (sum, payment) => sum + payment.amount,
    );
    final totalPlatform = state.adminPayments.fold<double>(
      0,
      (sum, payment) => sum + payment.platformFee,
    );
    final totalDriver = state.adminPayments.fold<double>(
      0,
      (sum, payment) => sum + payment.driverEarnings,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            MetricCard(
              label: 'Payments',
              value: state.adminPayments.length,
              icon: Icons.payments,
            ),
            MetricCard(
              label: 'Gross',
              value: '\$${totalAmount.toStringAsFixed(2)}',
              icon: Icons.account_balance,
            ),
            MetricCard(
              label: 'Platform',
              value: '\$${totalPlatform.toStringAsFixed(2)}',
              icon: Icons.trending_up,
            ),
            MetricCard(
              label: 'Driver paid',
              value: '\$${totalDriver.toStringAsFixed(2)}',
              icon: Icons.local_taxi,
            ),
          ],
        ),
        const SizedBox(height: 16),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Payment ledger',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 8),
              if (state.adminPayments.isEmpty)
                const EmptyState('No payments yet.'),
              for (final payment in state.adminPayments)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.payments, color: AppColors.accent),
                  title: Text(
                    formatMoney(
                      payment.amount,
                      currencySymbol: payment.currencySymbol,
                      currencyCode: payment.currencyCode,
                      currencyDecimals: payment.currencyDecimals,
                    ),
                    style: const TextStyle(fontWeight: FontWeight.w900),
                  ),
                  subtitle: Text(
                    'Ride ${payment.rideId} - ${payment.paymentMethod} - ${payment.status}',
                  ),
                  trailing: Text(
                    'Fee ${formatMoney(payment.platformFee, currencySymbol: payment.currencySymbol, currencyCode: payment.currencyCode, currencyDecimals: payment.currencyDecimals)}',
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _refunds(AppState state) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Refund requests',
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          if (state.adminRefunds.isEmpty)
            const EmptyState('No refund requests.'),
          for (final refund in state.adminRefunds)
            _RefundAdminTile(refund: refund),
        ],
      ),
    );
  }

  Widget _payouts(AppState state) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Payout requests',
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          if (state.adminPayouts.isEmpty)
            const EmptyState('No payout requests.'),
          for (final payout in state.adminPayouts)
            _PayoutAdminTile(payout: payout),
        ],
      ),
    );
  }

  IconData _roleIcon(UserRole role) {
    return switch (role) {
      UserRole.rider => Icons.person,
      UserRole.driver => Icons.local_taxi,
      UserRole.admin => Icons.admin_panel_settings,
    };
  }
}

class _AdminHeader extends StatelessWidget {
  const _AdminHeader({required this.section, required this.onChanged});

  final int section;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<int>(
      segments: const [
        ButtonSegment(
          value: 0,
          icon: Icon(Icons.dashboard),
          label: Text('Overview'),
        ),
        ButtonSegment(
          value: 1,
          icon: Icon(Icons.local_taxi),
          label: Text('Drivers'),
        ),
        ButtonSegment(value: 2, icon: Icon(Icons.route), label: Text('Rides')),
        ButtonSegment(
          value: 3,
          icon: Icon(Icons.payments),
          label: Text('Payments'),
        ),
        ButtonSegment(
          value: 4,
          icon: Icon(Icons.replay),
          label: Text('Refunds'),
        ),
        ButtonSegment(
          value: 5,
          icon: Icon(Icons.account_balance_wallet),
          label: Text('Payouts'),
        ),
        ButtonSegment(
          value: 6,
          icon: Icon(Icons.support_agent),
          label: Text('Support'),
        ),
      ],
      selected: {section},
      onSelectionChanged: (value) => onChanged(value.first),
    );
  }
}

class _RideAdminTile extends StatefulWidget {
  const _RideAdminTile({required this.ride});

  final Ride ride;

  @override
  State<_RideAdminTile> createState() => _RideAdminTileState();
}

class _RideAdminTileState extends State<_RideAdminTile> {
  late String _status = widget.ride.status;
  final _reason = TextEditingController(text: 'Operations review');

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const statuses = [
      'requested',
      'searching',
      'accepted',
      'driver_arriving',
      'arrived',
      'in_progress',
      'completed',
      'cancelled',
    ];
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TripCard(ride: widget.ride),
          if (widget.ride.status == 'completed') ReceiptCard(ride: widget.ride),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: _status,
                  decoration: const InputDecoration(
                    labelText: 'Operations status',
                    border: OutlineInputBorder(),
                  ),
                  items: statuses
                      .map(
                        (status) => DropdownMenuItem(
                          value: status,
                          child: Text(status),
                        ),
                      )
                      .toList(),
                  onChanged: (value) =>
                      setState(() => _status = value ?? _status),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton(
                onPressed: () => context.read<AppState>().updateAdminRideStatus(
                      widget.ride.id,
                      _status,
                      reason: _reason.text,
                    ),
                child: const Text('Apply'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          AppTextField(controller: _reason, label: 'Operations note'),
        ],
      ),
    );
  }
}

class _DriverAdminTile extends StatelessWidget {
  const _DriverAdminTile({required this.driver});

  final DriverProfile driver;

  @override
  Widget build(BuildContext context) {
    final state = context.read<AppState>();
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const CircleAvatar(child: Icon(Icons.local_taxi)),
            title: Text(driver.user?.name ?? driver.userId),
            subtitle: Text(
              '${driver.verificationStatus} - ${driver.driverStatus} - ${driver.vehicleColor} ${driver.vehicleMake} ${driver.vehicleModel} - ${driver.licensePlate}',
            ),
            trailing: RideStatusBadge(driver.verificationStatus),
          ),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              FilledButton.tonalIcon(
                onPressed: () =>
                    state.updateDriverVerification(driver.id, 'approve'),
                icon: const Icon(Icons.check),
                label: const Text('Approve'),
              ),
              OutlinedButton.icon(
                onPressed: () =>
                    state.updateDriverVerification(driver.id, 'reject'),
                icon: const Icon(Icons.close),
                label: const Text('Reject'),
              ),
              OutlinedButton.icon(
                onPressed: () =>
                    state.updateDriverVerification(driver.id, 'suspend'),
                icon: const Icon(Icons.block),
                label: const Text('Suspend'),
              ),
              OutlinedButton.icon(
                onPressed: () =>
                    state.updateDriverVerification(driver.id, 'unsuspend'),
                icon: const Icon(Icons.restore),
                label: const Text('Unsuspend'),
              ),
            ],
          ),
          if (driver.documents.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Documents', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            for (final document in driver.documents)
              _DriverDocumentReviewRow(driver: driver, document: document),
          ],
        ],
      ),
    );
  }
}

class _DriverDocumentReviewRow extends StatefulWidget {
  const _DriverDocumentReviewRow({
    required this.driver,
    required this.document,
  });

  final DriverProfile driver;
  final Map<String, dynamic> document;

  @override
  State<_DriverDocumentReviewRow> createState() =>
      _DriverDocumentReviewRowState();
}

class _DriverDocumentReviewRowState extends State<_DriverDocumentReviewRow> {
  late String _status = widget.document['status'] as String? ?? 'submitted';
  final _note = TextEditingController(text: 'Reviewed by operations.');

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const statuses = ['submitted', 'approved', 'rejected', 'expired'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.description),
          title: Text(widget.document['label'] as String? ?? ''),
          subtitle: Text(widget.document['identifier'] as String? ?? ''),
          trailing: RideStatusBadge(_status),
        ),
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: _status,
                decoration: const InputDecoration(
                  labelText: 'Document status',
                  border: OutlineInputBorder(),
                ),
                items: statuses
                    .map(
                      (status) => DropdownMenuItem(
                        value: status,
                        child: Text(status),
                      ),
                    )
                    .toList(),
                onChanged: (value) =>
                    setState(() => _status = value ?? _status),
              ),
            ),
            const SizedBox(width: 10),
            FilledButton.tonal(
              onPressed: () =>
                  context.read<AppState>().updateDriverDocumentStatus(
                        widget.driver.id,
                        widget.document['id'] as String,
                        _status,
                        _note.text,
                      ),
              child: const Text('Review'),
            ),
          ],
        ),
        const SizedBox(height: 8),
        AppTextField(controller: _note, label: 'Review note'),
        const SizedBox(height: 8),
      ],
    );
  }
}

class _TicketAdminTile extends StatefulWidget {
  const _TicketAdminTile({required this.ticket});

  final SupportTicket ticket;

  @override
  State<_TicketAdminTile> createState() => _TicketAdminTileState();
}

class _TicketAdminTileState extends State<_TicketAdminTile> {
  late String _status = widget.ticket.status;
  final _reply = TextEditingController(text: 'We are reviewing this ticket.');

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const statuses = ['open', 'in_review', 'resolved', 'closed'];
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.confirmation_number),
            title: Text('${widget.ticket.category} - ${widget.ticket.status}'),
            subtitle: Text(
              widget.ticket.replies.isEmpty
                  ? widget.ticket.message
                  : '${widget.ticket.message}\n${widget.ticket.replies.length} replies',
            ),
          ),
          if (widget.ticket.replies.isNotEmpty) ...[
            for (final reply in widget.ticket.replies.take(3))
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  reply.role == 'admin' ? Icons.support_agent : Icons.person,
                ),
                title: Text(reply.userName),
                subtitle: Text(reply.message),
              ),
          ],
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: _status,
                  decoration: const InputDecoration(
                    labelText: 'Status',
                    border: OutlineInputBorder(),
                  ),
                  items: statuses
                      .map(
                        (item) =>
                            DropdownMenuItem(value: item, child: Text(item)),
                      )
                      .toList(),
                  onChanged: (value) =>
                      setState(() => _status = value ?? _status),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton(
                onPressed: () => context
                    .read<AppState>()
                    .updateSupportTicketStatus(widget.ticket.id, _status),
                child: const Text('Update'),
              ),
            ],
          ),
          const SizedBox(height: 10),
          AppTextField(
            controller: _reply,
            label: 'Reply',
            minLines: 2,
            maxLines: 4,
          ),
          const SizedBox(height: 8),
          FilledButton.tonalIcon(
            onPressed: () async {
              await context
                  .read<AppState>()
                  .replyToSupportTicket(widget.ticket.id, _reply.text);
              if (mounted) _reply.clear();
            },
            icon: const Icon(Icons.reply),
            label: const Text('Send reply'),
          ),
        ],
      ),
    );
  }
}

class _RefundAdminTile extends StatefulWidget {
  const _RefundAdminTile({required this.refund});

  final Map<String, dynamic> refund;

  @override
  State<_RefundAdminTile> createState() => _RefundAdminTileState();
}

class _RefundAdminTileState extends State<_RefundAdminTile> {
  late String _status = widget.refund['status'] as String? ?? 'requested';
  late final TextEditingController _amount = TextEditingController(
    text:
        ((widget.refund['amount'] as num?)?.toDouble() ?? 0).toStringAsFixed(2),
  );
  late final TextEditingController _note = TextEditingController(
    text: widget.refund['adminNote'] as String? ?? 'Operations refund review.',
  );

  @override
  void dispose() {
    _amount.dispose();
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const statuses = ['requested', 'in_review', 'approved', 'rejected', 'paid'];
    final amount = (widget.refund['amount'] as num?)?.toDouble() ?? 0;
    final symbol = widget.refund['currencySymbol'] as String? ?? r'$';
    final code = widget.refund['currencyCode'] as String? ?? 'USD';
    final decimals = (widget.refund['currencyDecimals'] as num?)?.toInt() ?? 2;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.replay, color: AppColors.accent),
            title: Text(
              formatMoney(
                amount,
                currencySymbol: symbol,
                currencyCode: code,
                currencyDecimals: decimals,
              ),
              style: const TextStyle(fontWeight: FontWeight.w900),
            ),
            subtitle: Text(
              '${widget.refund['reason'] ?? 'Refund'} - ride ${widget.refund['rideId'] ?? ''}',
            ),
            trailing: RideStatusBadge(_status),
          ),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: _status,
                  decoration: const InputDecoration(
                    labelText: 'Refund status',
                    border: OutlineInputBorder(),
                  ),
                  items: statuses
                      .map(
                        (item) =>
                            DropdownMenuItem(value: item, child: Text(item)),
                      )
                      .toList(),
                  onChanged: (value) =>
                      setState(() => _status = value ?? _status),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton(
                onPressed: () => context.read<AppState>().updateRefundStatus(
                      widget.refund['id'] as String,
                      _status,
                      amount: double.tryParse(_amount.text.trim()),
                      adminNote: _note.text,
                    ),
                child: const Text('Update'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          AppTextField(
            controller: _amount,
            label: 'Refund amount',
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 8),
          AppTextField(controller: _note, label: 'Admin note'),
        ],
      ),
    );
  }
}

class _PayoutAdminTile extends StatefulWidget {
  const _PayoutAdminTile({required this.payout});

  final Map<String, dynamic> payout;

  @override
  State<_PayoutAdminTile> createState() => _PayoutAdminTileState();
}

class _PayoutAdminTileState extends State<_PayoutAdminTile> {
  late String _status = widget.payout['status'] as String? ?? 'requested';
  late final TextEditingController _note = TextEditingController(
    text: widget.payout['adminNote'] as String? ?? 'Payout reviewed.',
  );

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const statuses = ['requested', 'in_review', 'approved', 'rejected', 'paid'];
    final amount = (widget.payout['amount'] as num?)?.toDouble() ?? 0;
    final symbol = widget.payout['currencySymbol'] as String? ?? r'$';
    final code = widget.payout['currencyCode'] as String? ?? 'USD';
    final decimals = (widget.payout['currencyDecimals'] as num?)?.toInt() ?? 2;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(
              Icons.account_balance_wallet,
              color: AppColors.accent,
            ),
            title: Text(
              formatMoney(
                amount,
                currencySymbol: symbol,
                currencyCode: code,
                currencyDecimals: decimals,
              ),
              style: const TextStyle(fontWeight: FontWeight.w900),
            ),
            subtitle: Text(
              '${widget.payout['note'] ?? 'Payout'} - driver ${widget.payout['driverId'] ?? ''}',
            ),
            trailing: RideStatusBadge(_status),
          ),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: _status,
                  decoration: const InputDecoration(
                    labelText: 'Payout status',
                    border: OutlineInputBorder(),
                  ),
                  items: statuses
                      .map(
                        (item) =>
                            DropdownMenuItem(value: item, child: Text(item)),
                      )
                      .toList(),
                  onChanged: (value) =>
                      setState(() => _status = value ?? _status),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton(
                onPressed: () => context.read<AppState>().updatePayoutStatus(
                      widget.payout['id'] as String,
                      _status,
                      adminNote: _note.text,
                    ),
                child: const Text('Update'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          AppTextField(controller: _note, label: 'Admin note'),
        ],
      ),
    );
  }
}

class _AdminSidebar extends StatelessWidget {
  const _AdminSidebar({required this.state});

  final AppState state;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Payments', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              if (state.adminPayments.isEmpty)
                const EmptyState('No payments yet.'),
              for (final payment in state.adminPayments)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.payments),
                  title: Text(
                    '${formatMoney(payment.amount, currencySymbol: payment.currencySymbol, currencyCode: payment.currencyCode, currencyDecimals: payment.currencyDecimals)} - ${payment.status}',
                  ),
                  subtitle: Text(
                    'Platform ${formatMoney(payment.platformFee, currencySymbol: payment.currencySymbol, currencyCode: payment.currencyCode, currencyDecimals: payment.currencyDecimals)} - Driver ${formatMoney(payment.driverEarnings, currencySymbol: payment.currencySymbol, currencyCode: payment.currencyCode, currencyDecimals: payment.currencyDecimals)}',
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Data controls',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 10),
              const Text(
                'Reset clears current sessions and restores seed accounts, drivers, rides, payments, and tickets.',
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: state.resetAppData,
                icon: const Icon(Icons.restart_alt),
                label: const Text('Reset app data'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
