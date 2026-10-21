_'enum UserRole { rider, driver, admin }

String formatMoney(
  double value, {
  String currencySymbol = r'$',
  String currencyCode = 'USD',
  int currencyDecimals = 2,
}) {
  final decimals = currencyDecimals.clamp(0, 2);
  final prefix = value < 0 ? '-' : '';
  final formatted = value.abs().toStringAsFixed(decimals);
  return '$prefix$currencySymbol$formatted';
}

UserRole roleFromString(String value) {
  return UserRole.values.firstWhere(
    (role) => role.name == value,
    orElse: () => UserRole.rider,
  );
}

class AppUser {
  const AppUser({
    required this.id,
    required this.name,
    required this.email,
    required this.phone,
    required this.role,
    required this.isVerified,
  });

  factory AppUser.fromJson(Map<String, dynamic> json) {
    return AppUser(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      email: json['email'] as String? ?? '',
      phone: json['phone'] as String? ?? '',
      role: roleFromString(json['role'] as String? ?? 'rider'),
      isVerified: json['isVerified'] as bool? ?? false,
    );
  }

  final String id;
  final String name;
  final String email;
  final String phone;
  final UserRole role;
  final bool isVerified;
}

class LocationPoint {
  const LocationPoint({
    required this.address,
    required this.latitude,
    required this.longitude,
    this.id = '',
    this.cityId = '',
  });

  factory LocationPoint.fromJson(Map<String, dynamic> json) {
    return LocationPoint(
      id: json['id'] as String? ?? '',
      cityId: json['cityId'] as String? ?? '',
      address: json['address'] as String? ?? '',
      latitude: (json['latitude'] as num?)?.toDouble() ?? 0,
      longitude: (json['longitude'] as num?)?.toDouble() ?? 0,
    );
  }

  final String address;
  final double latitude;
  final double longitude;
  final String id;
  final String cityId;

  Map<String, dynamic> toRidePayload(String prefix) => {
    '${prefix}Address': address,
    '${prefix}Latitude': latitude,
    '${prefix}Longitude': longitude,
  };
}

class ServiceCity {
  const ServiceCity({
    required this.id,
    required this.name,
    required this.region,
    required this.centerLatitude,
    required this.centerLongitude,
    required this.radiusKm,
    required this.currencyCode,
    required this.currencySymbol,
    required this.currencyDecimals,
    required this.locations,
  });

  factory ServiceCity.fromJson(Map<String, dynamic> json) {
    return ServiceCity(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      region: json['region'] as String? ?? '',
      centerLatitude: (json['centerLatitude'] as num?)?.toDouble() ?? 34.0522,
      centerLongitude:
          (json['centerLongitude'] as num?)?.toDouble() ?? -118.2437,
      radiusKm: (json['radiusKm'] as num?)?.toDouble() ?? 60,
      currencyCode: json['currencyCode'] as String? ?? 'USD',
      currencySymbol: json['currencySymbol'] as String? ?? r'$',
      currencyDecimals: (json['currencyDecimals'] as num?)?.toInt() ?? 2,
      locations: ((json['locations'] as List?) ?? [])
          .map(
            (item) =>
                LocationPoint.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList(),
    );
  }

  final String id;
  final String name;
  final String region;
  final double centerLatitude;
  final double centerLongitude;
  final double radiusKm;
  final String currencyCode;
  final String currencySymbol;
  final int currencyDecimals;
  final List<LocationPoint> locations;

  String get label => '$name, $region';

  LocationPoint get centerLocation => LocationPoint(
    id: '${id}_center',
    cityId: id,
    address: '$name service area',
    latitude: centerLatitude,
    longitude: centerLongitude,
  );
}

class SavedPlace {
  const SavedPlace({
    required this.id,
    required this.label,
    required this.address,
    required this.latitude,
    required this.longitude,
  });

  factory SavedPlace.fromJson(Map<String, dynamic> json) {
    return SavedPlace(
      id: json['id'] as String? ?? '',
      label: json['label'] as String? ?? '',
      address: json['address'] as String? ?? '',
      latitude: (json['latitude'] as num?)?.toDouble() ?? 0,
      longitude: (json['longitude'] as num?)?.toDouble() ?? 0,
    );
  }

  final String id;
  final String label;
  final String address;
  final double latitude;
  final double longitude;

  LocationPoint get location =>
      LocationPoint(address: address, latitude: latitude, longitude: longitude);
}

class PaymentMethod {
  const PaymentMethod({
    required this.id,
    required this.type,
    required this.brand,
    required this.label,
    required this.last4,
    required this.isDefault,
  });

  factory PaymentMethod.fromJson(Map<String, dynamic> json) {
    return PaymentMethod(
      id: json['id'] as String? ?? '',
      type: json['type'] as String? ?? 'card',
      brand: json['brand'] as String? ?? 'Card',
      label: json['label'] as String? ?? 'Payment method',
      last4: json['last4'] as String? ?? '',
      isDefault: json['isDefault'] as bool? ?? false,
    );
  }

  final String id;
  final String type;
  final String brand;
  final String label;
  final String last4;
  final bool isDefault;
}

class RideOptionQuote {
  const RideOptionQuote({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.multiplier,
    required this.estimatedTotal,
    required this.currencyCode,
    required this.currencySymbol,
    required this.currencyDecimals,
  });

  factory RideOptionQuote.fromJson(Map<String, dynamic> json) {
    return RideOptionQuote(
      id: json['id'] as String? ?? 'standard',
      title: json['title'] as String? ?? 'Standard',
      subtitle: json['subtitle'] as String? ?? '',
      multiplier: (json['multiplier'] as num?)?.toDouble() ?? 1,
      estimatedTotal: (json['estimatedTotal'] as num?)?.toDouble() ?? 0,
      currencyCode: json['currencyCode'] as String? ?? 'USD',
      currencySymbol: json['currencySymbol'] as String? ?? r'$',
      currencyDecimals: (json['currencyDecimals'] as num?)?.toInt() ?? 2,
    );
  }

  final String id;
  final String title;
  final String subtitle;
  final double multiplier;
  final double estimatedTotal;
  final String currencyCode;
  final String currencySymbol;
  final int currencyDecimals;
}

class DriverProfile {
  const DriverProfile({
    required this.id,
    required this.userId,
    required this.licenseNumber,
    required this.vehicleMake,
    required this.vehicleModel,
    required this.vehicleYear,
    required this.licensePlate,
    required this.vehicleColor,
    required this.verificationStatus,
    required this.driverStatus,
    required this.currentLatitude,
    required this.currentLongitude,
    required this.averageRating,
    required this.totalTrips,
    this.documents = const [],
    this.documentSummary = const {},
    this.user,
  });

  factory DriverProfile.fromJson(Map<String, dynamic> json) {
    return DriverProfile(
      id: json['id'] as String? ?? '',
      userId: json['userId'] as String? ?? '',
      licenseNumber: json['licenseNumber']?.toString() ?? '',
      vehicleMake: json['vehicleMake']?.toString() ?? '',
      vehicleModel: json['vehicleModel']?.toString() ?? '',
      vehicleYear: json['vehicleYear']?.toString() ?? '',
      licensePlate: json['licensePlate']?.toString() ?? '',
      vehicleColor: json['vehicleColor']?.toString() ?? '',
      verificationStatus: json['verificationStatus'] as String? ?? 'pending',
      driverStatus: json['driverStatus'] as String? ?? 'offline',
      currentLatitude: (json['currentLatitude'] as num?)?.toDouble() ?? 34.0522,
      currentLongitude:
          (json['currentLongitude'] as num?)?.toDouble() ?? -118.2437,
      averageRating: (json['averageRating'] as num?)?.toDouble() ?? 5,
      totalTrips: (json['totalTrips'] as num?)?.toInt() ?? 0,
      documents: ((json['documents'] as List?) ?? [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList(),
      documentSummary: json['documentSummary'] is Map
          ? Map<String, dynamic>.from(json['documentSummary'] as Map)
          : const {},
      user: json['user'] is Map<String, dynamic>
          ? AppUser.fromJson(json['user'] as Map<String, dynamic>)
          : null,
    );
  }

  final String id;
  final String userId;
  final String licenseNumber;
  final String vehicleMake;
  final String vehicleModel;
  final String vehicleYear;
  final String licensePlate;
  final String vehicleColor;
  final String verificationStatus;
  final String driverStatus;
  final double currentLatitude;
  final double currentLongitude;
  final double averageRating;
  final int totalTrips;
  final List<Map<String, dynamic>> documents;
  final Map<String, dynamic> documentSummary;
  final AppUser? user;

  bool get isApproved => verificationStatus == 'approved';
  bool get isComplete {
    return licenseNumber.isNotEmpty &&
        vehicleMake.isNotEmpty &&
        vehicleModel.isNotEmpty &&
        vehicleYear.isNotEmpty &&
        licensePlate.isNotEmpty &&
        vehicleColor.isNotEmpty;
  }

  bool get documentsComplete => documentSummary['status'] == 'complete';
}

class FareBreakdown {
  const FareBreakdown({
    required this.baseFare,
    required this.distanceFare,
    required this.timeFare,
    required this.serviceFee,
    required this.surgeMultiplier,
    required this.estimatedTotal,
    required this.currencyCode,
    required this.currencySymbol,
    required this.currencyDecimals,
    this.pickupTimeMultiplier = 1,
    this.pickupTimeLabel = '',
    this.pickupTimeAdjustment = 0,
    this.waypointFee = 0,
    this.subtotalBeforeDiscount = 0,
    this.discountAmount = 0,
    this.promoCode = '',
    this.promoTitle = '',
    this.rideTier = 'standard',
    this.rideTierTitle = 'Standard',
  });

  factory FareBreakdown.fromJson(Map<String, dynamic> json) {
    return FareBreakdown(
      baseFare: (json['baseFare'] as num?)?.toDouble() ?? 0,
      distanceFare: (json['distanceFare'] as num?)?.toDouble() ?? 0,
      timeFare: (json['timeFare'] as num?)?.toDouble() ?? 0,
      serviceFee: (json['serviceFee'] as num?)?.toDouble() ?? 0,
      surgeMultiplier: (json['surgeMultiplier'] as num?)?.toDouble() ?? 1,
      estimatedTotal: (json['estimatedTotal'] as num?)?.toDouble() ?? 0,
      currencyCode: json['currencyCode'] as String? ?? 'USD',
      currencySymbol: json['currencySymbol'] as String? ?? r'$',
      currencyDecimals: (json['currencyDecimals'] as num?)?.toInt() ?? 2,
      pickupTimeMultiplier:
          (json['pickupTimeMultiplier'] as num?)?.toDouble() ?? 1,
      pickupTimeLabel: json['pickupTimeLabel'] as String? ?? '',
      pickupTimeAdjustment:
          (json['pickupTimeAdjustment'] as num?)?.toDouble() ?? 0,
      waypointFee: (json['waypointFee'] as num?)?.toDouble() ?? 0,
      subtotalBeforeDiscount:
          (json['subtotalBeforeDiscount'] as num?)?.toDouble() ?? 0,
      discountAmount: (json['discountAmount'] as num?)?.toDouble() ?? 0,
      promoCode: json['promoCode'] as String? ?? '',
      promoTitle: json['promoTitle'] as String? ?? '',
      rideTier: json['rideTier'] as String? ?? 'standard',
      rideTierTitle: json['rideTierTitle'] as String? ?? 'Standard',
    );
  }

  final double baseFare;
  final double distanceFare;
  final double timeFare;
  final double serviceFee;
  final double surgeMultiplier;
  final double estimatedTotal;
  final String currencyCode;
  final String currencySymbol;
  final int currencyDecimals;
  final double pickupTimeMultiplier;
  final String pickupTimeLabel;
  final double pickupTimeAdjustment;
  final double waypointFee;
  final double subtotalBeforeDiscount;
  final double discountAmount;
  final String promoCode;
  final String promoTitle;
  final String rideTier;
  final String rideTierTitle;
}

class PaymentRecord {
  const PaymentRecord({
    required this.id,
    required this.rideId,
    required this.amount,
    required this.platformFee,
    required this.driverEarnings,
    required this.currencyCode,
    required this.currencySymbol,
    required this.currencyDecimals,
    required this.paymentMethod,
    required this.status,
  });

  factory PaymentRecord.fromJson(Map<String, dynamic> json) {
    return PaymentRecord(
      id: json['id'] as String? ?? '',
      rideId: json['rideId'] as String? ?? '',
      amount: (json['amount'] as num?)?.toDouble() ?? 0,
      platformFee: (json['platformFee'] as num?)?.toDouble() ?? 0,
      driverEarnings: (json['driverEarnings'] as num?)?.toDouble() ?? 0,
      currencyCode: json['currencyCode'] as String? ?? 'USD',
      currencySymbol: json['currencySymbol'] as String? ?? r'$',
      currencyDecimals: (json['currencyDecimals'] as num?)?.toInt() ?? 2,
      paymentMethod: json['paymentMethod'] as String? ?? 'card_on_file',
      status: json['status'] as String? ?? 'pending',
    );
  }

  final String id;
  final String rideId;
  final double amount;
  final double platformFee;
  final double driverEarnings;
  final String currencyCode;
  final String currencySymbol;
  final int currencyDecimals;
  final String paymentMethod;
  final String status;
}

class RideTimelineEntry {
  const RideTimelineEntry({
    required this.status,
    required this.label,
    required this.at,
  });

  factory RideTimelineEntry.fromJson(Map<String, dynamic> json) {
    return RideTimelineEntry(
      status: json['status'] as String? ?? '',
      label: json['label'] as String? ?? '',
      at: json['at'] as String? ?? '',
    );
  }

  final String status;
  final String label;
  final String at;
}

class Ride {
  const Ride({
    required this.id,
    required this.status,
    required this.pickupAddress,
    required this.pickupLatitude,
    required this.pickupLongitude,
    required this.destinationAddress,
    required this.destinationLatitude,
    required this.destinationLongitude,
    this.waypoints = const [],
    required this.estimatedDistance,
    required this.estimatedDuration,
    required this.estimatedFare,
    required this.currencyCode,
    required this.currencySymbol,
    required this.currencyDecimals,
    required this.paymentStatus,
    required this.createdAt,
    this.rider,
    this.driver,
    this.driverProfile,
    this.payment,
    this.fareBreakdown,
    this.finalFare,
    this.finalDistance,
    this.finalDuration,
    this.driverDistanceToPickupKm,
    this.driverDistanceToDestinationKm,
    this.scheduledFor = '',
    this.automationFlow = const {},
    this.timeline = const [],
    this.messages = const [],
  });

  factory Ride.fromJson(Map<String, dynamic> json) {
    return Ride(
      id: json['id'] as String? ?? '',
      status: json['status'] as String? ?? 'requested',
      pickupAddress: json['pickupAddress'] as String? ?? '',
      pickupLatitude: (json['pickupLatitude'] as num?)?.toDouble() ?? 34.0522,
      pickupLongitude:
          (json['pickupLongitude'] as num?)?.toDouble() ?? -118.2437,
      destinationAddress: json['destinationAddress'] as String? ?? '',
      destinationLatitude:
          (json['destinationLatitude'] as num?)?.toDouble() ?? 34.0100,
      destinationLongitude:
          (json['destinationLongitude'] as num?)?.toDouble() ?? -118.4960,
      waypoints: ((json['waypoints'] as List?) ?? [])
          .map(
            (item) =>
                LocationPoint.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList(),
      estimatedDistance: (json['estimatedDistance'] as num?)?.toDouble() ?? 0,
      estimatedDuration: (json['estimatedDuration'] as num?)?.toInt() ?? 0,
      estimatedFare: (json['estimatedFare'] as num?)?.toDouble() ?? 0,
      currencyCode:
          json['currencyCode'] as String? ??
          (json['fareBreakdown'] is Map
              ? (json['fareBreakdown'] as Map)['currencyCode'] as String?
              : null) ??
          'USD',
      currencySymbol:
          json['currencySymbol'] as String? ??
          (json['fareBreakdown'] is Map
              ? (json['fareBreakdown'] as Map)['currencySymbol'] as String?
              : null) ??
          r'$',
      currencyDecimals:
          (json['currencyDecimals'] as num?)?.toInt() ??
          (json['fareBreakdown'] is Map
              ? ((json['fareBreakdown'] as Map)['currencyDecimals'] as num?)
                    ?.toInt()
              : null) ??
          2,
      finalFare: (json['finalFare'] as num?)?.toDouble(),
      finalDistance: (json['finalDistance'] as num?)?.toDouble(),
      finalDuration: (json['finalDuration'] as num?)?.toInt(),
      driverDistanceToPickupKm: (json['driverDistanceToPickupKm'] as num?)
          ?.toDouble(),
      driverDistanceToDestinationKm:
          (json['driverDistanceToDestinationKm'] as num?)?.toDouble(),
      paymentStatus: json['paymentStatus'] as String? ?? 'pending',
      createdAt: json['createdAt'] as String? ?? '',
      scheduledFor: json['scheduledFor'] as String? ?? '',
      automationFlow: json['automationFlow'] is Map
          ? Map<String, dynamic>.from(json['automationFlow'] as Map)
          : const {},
      rider: json['rider'] is Map<String, dynamic>
          ? AppUser.fromJson(json['rider'] as Map<String, dynamic>)
          : null,
      driver: json['driver'] is Map<String, dynamic>
          ? AppUser.fromJson(json['driver'] as Map<String, dynamic>)
          : null,
      driverProfile: json['driverProfile'] is Map<String, dynamic>
          ? DriverProfile.fromJson(
              json['driverProfile'] as Map<String, dynamic>,
            )
          : null,
      payment: json['payment'] is Map<String, dynamic>
          ? PaymentRecord.fromJson(json['payment'] as Map<String, dynamic>)
          : null,
      fareBreakdown: json['fareBreakdown'] is Map<String, dynamic>
          ? FareBreakdown.fromJson(
              json['fareBreakdown'] as Map<String, dynamic>,
            )
          : null,
      timeline: ((json['timeline'] as List?) ?? [])
          .map(
            (item) => RideTimelineEntry.fromJson(
              Map<String, dynamic>.from(item as Map),
            ),
          )
          .toList(),
      messages: ((json['messages'] as List?) ?? [])
          .map(
            (item) =>
                RideMessage.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList(),
    );
  }

  final String id;
  final String status;
  final String pickupAddress;
  final double pickupLatitude;
  final double pickupLongitude;
  final String destinationAddress;
  final double destinationLatitude;
  final double destinationLongitude;
  final List<LocationPoint> waypoints;
  final double estimatedDistance;
  final int estimatedDuration;
  final double estimatedFare;
  final String currencyCode;
  final String currencySymbol;
  final int currencyDecimals;
  final double? finalFare;
  final double? finalDistance;
  final int? finalDuration;
  final double? driverDistanceToPickupKm;
  final double? driverDistanceToDestinationKm;
  final String paymentStatus;
  final String createdAt;
  final String scheduledFor;
  final Map<String, dynamic> automationFlow;
  final AppUser? rider;
  final AppUser? driver;
  final DriverProfile? driverProfile;
  final PaymentRecord? payment;
  final FareBreakdown? fareBreakdown;
  final List<RideTimelineEntry> timeline;
  final List<RideMessage> messages;

  bool get isActive => !['completed', 'cancelled'].contains(status);
  bool get hasConfirmedDriver =>
      driver != null &&
      driverProfile != null &&
      [
        'accepted',
        'driver_arriving',
        'arrived',
        'in_progress',
        'completed',
      ].contains(status);
  bool get canCancel => [
    'scheduled',
    'requested',
    'searching',
    'accepted',
    'driver_arriving',
    'arrived',
  ].contains(status);
  bool get canRate => status == 'completed';
}

class RideMessage {
  const RideMessage({
    required this.id,
    required this.rideId,
    required this.senderId,
    required this.senderRole,
    required this.senderName,
    required this.body,
    required this.createdAt,
  });

  factory RideMessage.fromJson(Map<String, dynamic> json) {
    return RideMessage(
      id: json['id'] as String? ?? '',
      rideId: json['rideId'] as String? ?? '',
      senderId: json['senderId'] as String? ?? '',
      senderRole: json['senderRole'] as String? ?? 'rider',
      senderName: json['senderName'] as String? ?? '',
      body: json['body'] as String? ?? '',
      createdAt: json['createdAt'] as String? ?? '',
    );
  }

  final String id;
  final String rideId;
  final String senderId;
  final String senderRole;
  final String senderName;
  final String body;
  final String createdAt;
}

class SupportReply {
  const SupportReply({
    required this.id,
    required this.ticketId,
    required this.userId,
    required this.userName,
    required this.role,
    required this.message,
    required this.createdAt,
  });

  factory SupportReply.fromJson(Map<String, dynamic> json) {
    return SupportReply(
      id: json['id'] as String? ?? '',
      ticketId: json['ticketId'] as String? ?? '',
      userId: json['userId'] as String? ?? '',
      userName: json['userName'] as String? ?? '',
      role: json['role'] as String? ?? 'rider',
      message: json['message'] as String? ?? '',
      createdAt: json['createdAt'] as String? ?? '',
    );
  }

  final String id;
  final String ticketId;
  final String userId;
  final String userName;
  final String role;
  final String message;
  final String createdAt;
}

class SupportTicket {
  const SupportTicket({
    required this.id,
    required this.userId,
    required this.rideId,
    required this.category,
    required this.message,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    this.replies = const [],
  });

  factory SupportTicket.fromJson(Map<String, dynamic> json) {
    return SupportTicket(
      id: json['id'] as String? ?? '',
      userId: json['userId'] as String? ?? '',
      rideId: json['rideId'] as String? ?? '',
      category: json['category'] as String? ?? 'other',
      message: json['message'] as String? ?? '',
      status: json['status'] as String? ?? 'open',
      createdAt: json['createdAt'] as String? ?? '',
      updatedAt: json['updatedAt'] as String? ?? '',
      replies: ((json['replies'] as List?) ?? [])
          .map(
            (item) =>
                SupportReply.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList(),
    );
  }

  final String id;
  final String userId;
  final String rideId;
  final String category;
  final String message;
  final String status;
  final String createdAt;
  final String updatedAt;
  final List<SupportReply> replies;
}

class NotificationItem {
  const NotificationItem({
    required this.id,
    required this.type,
    required this.title,
    required this.message,
    required this.read,
    required this.createdAt,
  });

  factory NotificationItem.fromJson(Map<String, dynamic> json) {
    return NotificationItem(
      id: json['id'] as String? ?? '',
      type: json['type'] as String? ?? '',
      title: json['title'] as String? ?? '',
      message: json['message'] as String? ?? '',
      read: json['read'] as bool? ?? false,
      createdAt: json['createdAt'] as String? ?? '',
    );
  }

  final String id;
  final String type;
  final String title;
  final String message;
  final bool read;
  final String createdAt;
}
