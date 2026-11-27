import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/api/api_client.dart';
import '../core/config/app_config.dart';
import '../core/location/current_location_service.dart';
import '../shared/models/models.dart';
import '../shared/utils/ride_math.dart';

class AppState extends ChangeNotifier {
  AppState({required this.apiClient});

  final ApiClient apiClient;

  bool isLoading = true;
  String? errorMessage;
  AppUser? currentUser;
  DriverProfile? driverProfile;
  LocationPoint? currentLocation;
  List<LocationPoint> locations = const [];
  List<ServiceCity> serviceCities = const [];
  ServiceCity? selectedCity;
  FareBreakdown? currentFare;
  List<RideOptionQuote> rideOptions = [];
  List<SavedPlace> savedPlaces = [];
  List<PaymentMethod> paymentMethods = [];
  Ride? activeRide;
  Ride? latestCompletedRide;
  Ride? latestCancelledRide;
  List<Ride> rideHistory = [];
  List<Ride> scheduledRides = [];
  List<Ride> incomingRides = [];
  Map<String, dynamic> earnings = {};
  List<Map<String, dynamic>> driverDocuments = [];
  Map<String, dynamic> driverDocumentSummary = {};
  List<Map<String, dynamic>> driverPayouts = [];
  Map<String, dynamic> adminMetrics = {};
  List<AppUser> adminUsers = [];
  List<DriverProfile> adminDrivers = [];
  List<Ride> adminRides = [];
  List<PaymentRecord> adminPayments = [];
  List<Map<String, dynamic>> adminRefunds = [];
  List<Map<String, dynamic>> adminPayouts = [];
  List<SupportTicket> supportTickets = [];
  List<NotificationItem> notifications = [];
  List<Map<String, dynamic>> coupons = [];
  List<Map<String, dynamic>> paymentHistory = [];
  List<Map<String, dynamic>> refunds = [];
  List<Map<String, dynamic>> invoices = [];
  Timer? _poller;
  bool _isRefreshingForRole = false;
  String? _dismissedCompletedRideId;
  String? _dismissedCancelledRideId;

  Future<void> bootstrap() async {
    await _guard(() async {
      stopPolling();
      await apiClient.tokenStore.clear();
      currentUser = null;
      driverProfile = null;
      _clearRoleData();
      await apiClient.post('/dev/reset', {});
      final config = await apiClient.get('/config/bootstrap');
      serviceCities = ((config['serviceCities'] as List?) ?? [])
          .map(
            (item) =>
                ServiceCity.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList();
      locations = serviceCities.isNotEmpty
          ? serviceCities.expand((city) => city.locations).toList()
          : ((config['locations'] as Map<String, dynamic>? ?? {}).values)
              .map(
                (item) => LocationPoint.fromJson(
                  Map<String, dynamic>.from(item as Map),
                ),
              )
              .toList();
      currentLocation = _serviceLocationFor(
        await CurrentLocationService().resolveCurrentLocation(),
      );
    });
  }

  Future<void> refreshCurrentLocation() async {
    await _guard(() async {
      currentLocation = _serviceLocationFor(
        await CurrentLocationService().resolveCurrentLocation(),
      );
    });
  }

  void setSelectedCity(ServiceCity city) {
    selectedCity = city;
    currentLocation = city.centerLocation;
    currentFare = null;
    notifyListeners();
  }

  Future<void> login(String email, String password, UserRole role) async {
    await _guard(() async {
      final data = await apiClient.post('/auth/login', {
        'email': email,
        'password': password,
        'role': role.name,
      });
      await apiClient.tokenStore.writeToken(data['token'] as String);
      currentUser = AppUser.fromJson(
        Map<String, dynamic>.from(data['user'] as Map),
      );
      driverProfile = data['driverProfile'] is Map
          ? DriverProfile.fromJson(
              Map<String, dynamic>.from(data['driverProfile'] as Map),
            )
          : null;
      _clearRoleData();
      await refreshForRole(force: true);
    });
  }

  Future<void> register(
    String name,
    String email,
    String password,
    UserRole role,
  ) async {
    await _guard(() async {
      final data = await apiClient.post('/auth/register', {
        'name': name,
        'email': email,
        'password': password,
        'role': role.name,
      });
      await apiClient.tokenStore.writeToken(data['token'] as String);
      currentUser = AppUser.fromJson(
        Map<String, dynamic>.from(data['user'] as Map),
      );
      driverProfile = data['driverProfile'] is Map
          ? DriverProfile.fromJson(
              Map<String, dynamic>.from(data['driverProfile'] as Map),
            )
          : null;
      _clearRoleData();
      await refreshForRole(force: true);
    });
  }

  Future<void> logout() async {
    stopPolling();
    try {
      await apiClient.post('/auth/logout', {});
    } on ApiException catch (error) {
      if (error.code != 'NETWORK_UNAVAILABLE' &&
          error.code != 'AUTH_REQUIRED') {
        rethrow;
      }
    }
    await apiClient.tokenStore.clear();
    currentUser = null;
    driverProfile = null;
    _clearRoleData();
    notifyListeners();
  }

  Future<void> refreshForRole({bool force = false}) async {
    final user = currentUser;
    if (user == null) return;
    if (_isRefreshingForRole && !force) return;
    _isRefreshingForRole = true;
    try {
      if (user.role == UserRole.rider) await refreshRider();
      if (user.role == UserRole.driver) await refreshDriver();
      if (user.role == UserRole.admin) await refreshAdmin();
      await refreshNotifications();
      startPolling();
    } finally {
      _isRefreshingForRole = false;
    }
  }

  Future<void> estimateRide(
    LocationPoint pickup,
    LocationPoint destination, {
    List<LocationPoint> waypoints = const [],
    String rideTier = 'standard',
    String paymentMethod = 'card_on_file',
    String promoCode = '',
    DateTime? scheduledFor,
  }) async {
    await _guard(() async {
      final data = await apiClient.post('/rides/estimate', {
        ...pickup.toRidePayload('pickup'),
        ...destination.toRidePayload('destination'),
        'waypoints': waypoints.map(_locationPayload).toList(),
        'paymentMethod': paymentMethod,
        'rideTier': rideTier,
        'promoCode': promoCode,
        if (scheduledFor != null)
          'scheduledFor': scheduledFor.toIso8601String(),
      });
      currentFare = FareBreakdown.fromJson(
        Map<String, dynamic>.from(data['fareBreakdown'] as Map),
      );
      rideOptions = ((data['rideOptions'] as List?) ?? [])
          .map(
            (item) => RideOptionQuote.fromJson(
              Map<String, dynamic>.from(item as Map),
            ),
          )
          .toList();
    });
  }

  void clearFareEstimate() {
    if (currentFare == null) return;
    currentFare = null;
    notifyListeners();
  }

  void dismissLatestCompletedRide() {
    final ride = latestCompletedRide;
    if (ride == null) return;
    _dismissedCompletedRideId = ride.id;
    latestCompletedRide = null;
    currentFare = null;
    notifyListeners();
  }

  void dismissLatestCancelledRide() {
    final ride = latestCancelledRide;
    if (ride == null) return;
    _dismissedCancelledRideId = ride.id;
    latestCancelledRide = null;
    currentFare = null;
    notifyListeners();
  }

  Future<void> requestRide(
    LocationPoint pickup,
    LocationPoint destination, {
    List<LocationPoint> waypoints = const [],
    String rideTier = 'standard',
    String paymentMethod = 'card_on_file',
    String promoCode = '',
    DateTime? scheduledFor,
  }) async {
    await _guard(() async {
      final data = await apiClient.post('/rides/request', {
        ...pickup.toRidePayload('pickup'),
        ...destination.toRidePayload('destination'),
        'waypoints': waypoints.map(_locationPayload).toList(),
        'paymentMethod': paymentMethod,
        'rideTier': rideTier,
        'promoCode': promoCode,
        if (scheduledFor != null)
          'scheduledFor': scheduledFor.toIso8601String(),
      });
      activeRide = Ride.fromJson(
        Map<String, dynamic>.from(data['ride'] as Map),
      );
      latestCompletedRide = null;
      _dismissedCompletedRideId = null;
      currentFare = activeRide?.fareBreakdown;
      await refreshRider();
    });
  }

  Future<void> updateRideWaypoints(
    String rideId,
    List<LocationPoint> waypoints,
  ) async {
    await _guard(() async {
      final data = await apiClient.patch('/rides/$rideId/waypoints', {
        'waypoints': waypoints.map(_locationPayload).toList(),
      });
      activeRide = Ride.fromJson(
        Map<String, dynamic>.from(data['ride'] as Map),
      );
      currentFare = activeRide?.fareBreakdown;
      await refreshRider();
    });
  }

  Future<void> refreshRider() async {
    final active = await apiClient.get('/rides/active');
    activeRide = active['ride'] is Map
        ? Ride.fromJson(Map<String, dynamic>.from(active['ride'] as Map))
        : null;
    final scheduled = await apiClient.get('/rides/scheduled');
    scheduledRides = ((scheduled['rides'] as List?) ?? [])
        .map((item) => Ride.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();
    final history = await apiClient.get('/rides/history');
    rideHistory = ((history['rides'] as List?) ?? [])
        .map((item) => Ride.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();
    final latestCompleted =
        rideHistory.where((ride) => ride.status == 'completed').firstOrNull;
    latestCompletedRide = latestCompleted?.id == _dismissedCompletedRideId
        ? null
        : latestCompleted;
    final support = await apiClient.get('/support/tickets');
    supportTickets = ((support['tickets'] as List?) ?? [])
        .map(
          (item) =>
              SupportTicket.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList();
    final places = await apiClient.get('/rider/saved-places');
    savedPlaces = ((places['savedPlaces'] as List?) ?? [])
        .map(
          (item) => SavedPlace.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList();
    _applyRiderHomeMarket();
    final methods = await apiClient.get('/payments/methods');
    paymentMethods = ((methods['paymentMethods'] as List?) ?? [])
        .map(
          (item) =>
              PaymentMethod.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList();
    final couponsPayload = await apiClient.get('/rider/coupons');
    coupons = ((couponsPayload['coupons'] as List?) ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    final paymentPayload = await apiClient.get('/payments/history');
    paymentHistory = ((paymentPayload['payments'] as List?) ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    final refundPayload = await apiClient.get('/payments/refunds');
    refunds = ((refundPayload['refunds'] as List?) ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    final invoicePayload = await apiClient.get('/invoices');
    invoices = ((invoicePayload['invoices'] as List?) ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    notifyListeners();
  }

  Future<void> savePlace(String label, LocationPoint location) async {
    await _guard(() async {
      await apiClient.post('/rider/saved-places', {
        'label': label,
        'address': location.address,
        'latitude': location.latitude,
        'longitude': location.longitude,
      });
      await refreshRider();
    });
  }

  Future<void> deleteSavedPlace(String placeId) async {
    await _guard(() async {
      await apiClient.delete('/rider/saved-places/$placeId');
      savedPlaces = savedPlaces.where((place) => place.id != placeId).toList();
      notifyListeners();
    });
  }

  Future<void> addPaymentMethod({
    required String brand,
    required String last4,
    required String label,
  }) async {
    await _guard(() async {
      final payload = await apiClient.post('/payments/methods', {
        'brand': brand.trim(),
        'last4': last4.trim(),
        'label': label.trim(),
      });
      paymentMethods = ((payload['paymentMethods'] as List?) ?? [])
          .map(
            (item) =>
                PaymentMethod.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList();
    });
  }

  Future<void> setDefaultPaymentMethod(String methodId) async {
    await _guard(() async {
      final payload = await apiClient.patch(
        '/payments/methods/$methodId/default',
        {},
      );
      paymentMethods = ((payload['paymentMethods'] as List?) ?? [])
          .map(
            (item) =>
                PaymentMethod.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList();
    });
  }

  Future<void> deletePaymentMethod(String methodId) async {
    await _guard(() async {
      final payload = await apiClient.delete('/payments/methods/$methodId');
      paymentMethods = ((payload['paymentMethods'] as List?) ?? [])
          .map(
            (item) =>
                PaymentMethod.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList();
    });
  }

  Future<bool> validatePromo(String code) async {
    var valid = false;
    await _guard(() async {
      await apiClient.post('/promos/validate', {'code': code});
      valid = true;
    });
    return valid;
  }

  Future<void> requestRefund(String rideId, String reason) async {
    await _guard(() async {
      final payload = await apiClient.post('/payments/refunds', {
        'rideId': rideId,
        'reason': reason.trim(),
      });
      refunds = ((payload['refunds'] as List?) ?? [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
      await refreshNotifications();
    });
  }

  Future<void> generateInvoice(String rideId) async {
    await _guard(() async {
      final payload = await apiClient.post('/invoices', {'rideId': rideId});
      invoices = ((payload['invoices'] as List?) ?? [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
      await refreshNotifications();
    });
  }

  Future<void> cancelRide(
    String rideId, {
    String reason = 'Cancelled before pickup',
  }) async {
    await _guard(() async {
      final previousCompletedRideId = latestCompletedRide?.id ??
          rideHistory
              .where((ride) => ride.status == 'completed')
              .firstOrNull
              ?.id;
      final payload = await apiClient.post('/rides/$rideId/cancel', {
        'reason': reason,
      });
      final cancelledRide = payload['ride'] is Map
          ? Ride.fromJson(Map<String, dynamic>.from(payload['ride'] as Map))
          : null;
      if (currentUser?.role == UserRole.driver) {
        await refreshDriver();
      } else {
        await refreshRider();
        if (cancelledRide != null &&
            cancelledRide.status == 'cancelled' &&
            cancelledRide.id != _dismissedCancelledRideId) {
          latestCancelledRide = cancelledRide;
        }
        if (latestCompletedRide?.id == previousCompletedRideId) {
          _dismissedCompletedRideId = previousCompletedRideId;
          latestCompletedRide = null;
        }
        currentFare = null;
        notifyListeners();
      }
    });
  }

  Future<void> confirmBoarding(String rideId) async {
    await _guard(() async {
      await apiClient.post('/rides/$rideId/confirm-boarding', {});
      await refreshRider();
    });
  }

  Future<void> sendRideMessage(String rideId, String message) async {
    await _guard(() async {
      final payload = await apiClient.post('/rides/$rideId/messages', {
        'message': message,
      });
      if (payload['ride'] is Map<String, dynamic>) {
        final ride = Ride.fromJson(
          Map<String, dynamic>.from(payload['ride'] as Map),
        );
        if (activeRide?.id == ride.id) activeRide = ride;
        rideHistory = rideHistory
            .map((item) => item.id == ride.id ? ride : item)
            .toList();
      }
      if (currentUser?.role == UserRole.driver) {
        await refreshDriver();
      } else if (currentUser?.role == UserRole.rider) {
        await refreshRider();
      }
      await refreshNotifications();
      notifyListeners();
    });
  }

  Future<void> rateRide(String rideId, int score, String comment) async {
    await _guard(() async {
      await apiClient.post('/rides/$rideId/rating', {
        'score': score,
        'comment': comment,
      });
      if (currentUser?.role == UserRole.driver) {
        await refreshDriver();
      } else {
        await refreshRider();
      }
    });
  }

  Future<void> updateCurrentUser(String name, String phone) async {
    await _guard(() async {
      final data = await apiClient.patch('/users/me', {
        'name': name.trim(),
        'phone': phone.trim(),
      });
      currentUser = AppUser.fromJson(
        Map<String, dynamic>.from(data['user'] as Map),
      );
      if (data['driverProfile'] is Map) {
        driverProfile = DriverProfile.fromJson(
          Map<String, dynamic>.from(data['driverProfile'] as Map),
        );
      }
      notifyListeners();
    });
  }

  Future<void> saveDriverProfile(Map<String, dynamic> payload) async {
    await _guard(() async {
      final data = await apiClient.patch('/driver/profile', payload);
      driverProfile = DriverProfile.fromJson(
        Map<String, dynamic>.from(data['driverProfile'] as Map),
      );
      notifyListeners();
    });
  }

  Future<void> submitDriverDocument({
    required String type,
    required String identifier,
    String label = '',
    String expiresAt = '',
  }) async {
    await _guard(() async {
      final data = await apiClient.post('/driver/documents', {
        'type': type,
        'identifier': identifier.trim(),
        'label': label.trim(),
        'expiresAt': expiresAt.trim(),
      });
      driverDocuments = ((data['documents'] as List?) ?? [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
      driverDocumentSummary = Map<String, dynamic>.from(
        data['documentSummary'] as Map? ?? {},
      );
      if (data['driverProfile'] is Map) {
        driverProfile = DriverProfile.fromJson(
          Map<String, dynamic>.from(data['driverProfile'] as Map),
        );
      }
      notifyListeners();
    });
  }

  Future<void> requestDriverPayout(double amount, String note) async {
    await _guard(() async {
      final payload = await apiClient.post('/driver/payouts', {
        'amount': amount,
        'note': note.trim(),
      });
      driverPayouts = ((payload['payouts'] as List?) ?? [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
      await refreshDriver();
    });
  }

  Future<void> setDriverStatus(String status) async {
    await _guard(() async {
      final data = await apiClient.patch('/driver/status', {
        'driverStatus': status,
      });
      driverProfile = DriverProfile.fromJson(
        Map<String, dynamic>.from(data['driverProfile'] as Map),
      );
      await refreshDriver();
    });
  }

  Future<void> refreshDriver() async {
    final profile = await apiClient.get('/driver/profile');
    driverProfile = profile['driverProfile'] is Map
        ? DriverProfile.fromJson(
            Map<String, dynamic>.from(profile['driverProfile'] as Map),
          )
        : null;
    final incoming = await apiClient.get('/driver/incoming-rides');
    incomingRides = ((incoming['rides'] as List?) ?? [])
        .map((item) => Ride.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();
    final active = await apiClient.get('/driver/active-ride');
    activeRide = active['ride'] is Map
        ? Ride.fromJson(Map<String, dynamic>.from(active['ride'] as Map))
        : null;
    final earningsPayload = await apiClient.get('/driver/earnings');
    earnings = Map<String, dynamic>.from(
      earningsPayload['earnings'] as Map? ?? {},
    );
    rideHistory = ((earningsPayload['rides'] as List?) ?? [])
        .map((item) => Ride.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();
    final documentsPayload = await apiClient.get('/driver/documents');
    driverDocuments = ((documentsPayload['documents'] as List?) ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    driverDocumentSummary = Map<String, dynamic>.from(
      documentsPayload['documentSummary'] as Map? ?? {},
    );
    final payoutsPayload = await apiClient.get('/driver/payouts');
    driverPayouts = ((payoutsPayload['payouts'] as List?) ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    final support = await apiClient.get('/support/tickets');
    supportTickets = ((support['tickets'] as List?) ?? [])
        .map(
          (item) =>
              SupportTicket.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList();
    notifyListeners();
  }

  Future<void> acceptRide(String rideId) async {
    await _guard(() async {
      await apiClient.post('/driver/rides/$rideId/accept', {});
      await refreshDriver();
    });
  }

  Future<void> rejectRide(String rideId) async {
    await _guard(() async {
      await apiClient.post('/driver/rides/$rideId/reject', {});
      await refreshDriver();
    });
  }

  Future<void> generateIncomingRide() async {
    await _guard(() async {
      final payload = await apiClient.post('/driver/incoming-ride', {});
      incomingRides = ((payload['rides'] as List?) ?? [])
          .map((item) => Ride.fromJson(Map<String, dynamic>.from(item as Map)))
          .toList();
      await refreshDriver();
    });
  }

  Future<void> updateDriverRideStatus(String rideId, String status) async {
    await _guard(() async {
      await apiClient.patch('/driver/rides/$rideId/status', {'status': status});
      await refreshDriver();
    });
  }

  Future<void> refreshAdmin() async {
    final overview = await apiClient.get('/admin/overview');
    adminMetrics = Map<String, dynamic>.from(overview['metrics'] as Map? ?? {});
    adminUsers = ((await apiClient.get('/admin/users'))['users'] as List? ?? [])
        .map((item) => AppUser.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();
    adminDrivers =
        ((await apiClient.get('/admin/drivers'))['drivers'] as List? ?? [])
            .map(
              (item) => DriverProfile.fromJson(
                Map<String, dynamic>.from(item as Map),
              ),
            )
            .toList();
    adminRides = ((await apiClient.get('/admin/rides'))['rides'] as List? ?? [])
        .map((item) => Ride.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();
    adminPayments =
        ((await apiClient.get('/admin/payments'))['payments'] as List? ?? [])
            .map(
              (item) => PaymentRecord.fromJson(
                Map<String, dynamic>.from(item as Map),
              ),
            )
            .toList();
    adminRefunds =
        ((await apiClient.get('/admin/refunds'))['refunds'] as List? ?? [])
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
    adminPayouts =
        ((await apiClient.get('/admin/payouts'))['payouts'] as List? ?? [])
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
    supportTickets =
        ((await apiClient.get('/admin/support-tickets'))['tickets'] as List? ??
                [])
            .map(
              (item) => SupportTicket.fromJson(
                Map<String, dynamic>.from(item as Map),
              ),
            )
            .toList();
    notifyListeners();
  }

  Future<void> updateDriverVerification(String driverId, String action) async {
    await _guard(() async {
      await apiClient.patch('/admin/drivers/$driverId/$action', {});
      await refreshAdmin();
    });
  }

  Future<void> updateDriverDocumentStatus(
    String driverId,
    String documentId,
    String status,
    String note,
  ) async {
    await _guard(() async {
      await apiClient.patch('/admin/drivers/$driverId/documents/$documentId', {
        'status': status,
        'reviewNote': note.trim(),
      });
      await refreshAdmin();
    });
  }

  Future<void> updateAdminRideStatus(
    String rideId,
    String status, {
    String reason = '',
  }) async {
    await _guard(() async {
      await apiClient.patch('/admin/rides/$rideId/status', {
        'status': status,
        'reason': reason.trim(),
        'note': reason.trim(),
      });
      await refreshAdmin();
    });
  }

  Future<SupportTicket?> createSupportTicket(
    String message, {
    String category = 'safety concern',
    String rideId = '',
  }) async {
    SupportTicket? created;
    await _guard(() async {
      final payload = await apiClient.post('/support/tickets', {
        'message': message,
        'category': category,
        'rideId': rideId,
      });
      if (payload['ticket'] is Map) {
        created = SupportTicket.fromJson(
          Map<String, dynamic>.from(payload['ticket'] as Map),
        );
      }
      await refreshForRole();
    });
    return created;
  }

  Future<void> replyToSupportTicket(String ticketId, String message) async {
    await _guard(() async {
      await apiClient.post('/support/tickets/$ticketId/replies', {
        'message': message.trim(),
      });
      await refreshForRole(force: true);
    });
  }

  Future<void> updateSupportTicketStatus(String ticketId, String status) async {
    await _guard(() async {
      await apiClient.patch('/admin/support-tickets/$ticketId', {
        'status': status,
      });
      await refreshAdmin();
    });
  }

  Future<void> updateRefundStatus(
    String refundId,
    String status, {
    double? amount,
    String adminNote = '',
  }) async {
    await _guard(() async {
      await apiClient.patch('/admin/refunds/$refundId', {
        'status': status,
        if (amount != null) 'amount': amount,
        'adminNote': adminNote.trim(),
      });
      await refreshAdmin();
    });
  }

  Future<void> updatePayoutStatus(
    String payoutId,
    String status, {
    String adminNote = '',
  }) async {
    await _guard(() async {
      await apiClient.patch('/admin/payouts/$payoutId', {
        'status': status,
        'adminNote': adminNote.trim(),
      });
      await refreshAdmin();
    });
  }

  Future<void> refreshNotifications() async {
    if (currentUser == null) return;
    final payload = await apiClient.get('/notifications');
    notifications = ((payload['notifications'] as List?) ?? [])
        .map(
          (item) =>
              NotificationItem.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList();
  }

  Future<void> markNotificationRead(String notificationId) async {
    await _guard(() async {
      await apiClient.patch('/notifications/$notificationId/read', {});
      await refreshNotifications();
    });
  }

  Future<void> resetAppData() async {
    await _guard(() async {
      await apiClient.post('/dev/reset', {});
      await apiClient.tokenStore.clear();
      currentUser = null;
      driverProfile = null;
      _clearRoleData();
      stopPolling();
    });
  }

  void startPolling() {
    if (_poller != null) return;
    _poller = Timer.periodic(
      const Duration(seconds: AppConfig.pollingIntervalSeconds),
      (_) => _safeRefreshForRole(),
    );
  }

  void stopPolling() {
    _poller?.cancel();
    _poller = null;
  }

  @override
  void dispose() {
    stopPolling();
    super.dispose();
  }

  Future<void> _guard(Future<void> Function() action) async {
    isLoading = true;
    errorMessage = null;
    notifyListeners();
    try {
      await action();
    } catch (error) {
      errorMessage = error.toString();
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  Future<void> _safeRefreshForRole() async {
    try {
      await refreshForRole();
    } catch (error) {
      errorMessage = error.toString();
      notifyListeners();
    }
  }

  void _clearRoleData() {
    currentFare = null;
    rideOptions = [];
    activeRide = null;
    latestCompletedRide = null;
    latestCancelledRide = null;
    _dismissedCompletedRideId = null;
    _dismissedCancelledRideId = null;
    rideHistory = [];
    scheduledRides = [];
    incomingRides = [];
    earnings = {};
    driverDocuments = [];
    driverDocumentSummary = {};
    driverPayouts = [];
    adminMetrics = {};
    adminUsers = [];
    adminDrivers = [];
    adminRides = [];
    adminPayments = [];
    adminRefunds = [];
    adminPayouts = [];
    supportTickets = [];
    savedPlaces = [];
    paymentMethods = [];
    notifications = [];
    coupons = [];
    paymentHistory = [];
    refunds = [];
    invoices = [];
  }

  LocationPoint _serviceLocationFor(LocationPoint resolved) {
    if (serviceCities.isEmpty) return resolved;
    final matchingCity = resolved.cityId.isNotEmpty
        ? serviceCities.where((city) => city.id == resolved.cityId).firstOrNull
        : _cityContaining(resolved);
    selectedCity = matchingCity ??
        selectedCity ??
        serviceCities.where((city) => city.id == 'sf_bay').firstOrNull ??
        serviceCities.first;
    if (matchingCity != null) {
      return LocationPoint(
        id: resolved.id,
        cityId: matchingCity.id,
        address: resolved.address,
        latitude: resolved.latitude,
        longitude: resolved.longitude,
      );
    }
    return selectedCity!.centerLocation;
  }

  Map<String, dynamic> _locationPayload(LocationPoint point) => {
        'id': point.id,
        'cityId': point.cityId,
        'address': point.address,
        'latitude': point.latitude,
        'longitude': point.longitude,
      };

  void _applyRiderHomeMarket() {
    if (serviceCities.isEmpty || savedPlaces.isEmpty) return;
    final home = savedPlaces.firstWhere(
      (place) => place.label.toLowerCase() == 'home',
      orElse: () => savedPlaces.first,
    );
    final city = _cityContaining(home.location);
    if (city == null || city.id == selectedCity?.id) return;
    selectedCity = city;
    currentLocation = LocationPoint(
      id: home.id,
      cityId: city.id,
      address: home.address,
      latitude: home.latitude,
      longitude: home.longitude,
    );
    currentFare = null;
  }

  ServiceCity? _cityContaining(LocationPoint point) {
    ServiceCity? nearest;
    var nearestDistance = double.infinity;
    for (final city in serviceCities) {
      final distance = calculateHaversineDistance(
        startLatitude: city.centerLatitude,
        startLongitude: city.centerLongitude,
        endLatitude: point.latitude,
        endLongitude: point.longitude,
      );
      if (distance <= city.radiusKm && distance < nearestDistance) {
        nearest = city;
        nearestDistance = distance;
      }
    }
    return nearest;
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
