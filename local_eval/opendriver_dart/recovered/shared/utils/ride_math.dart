import 'dart:math';

class RideTransition {
  const RideTransition(this.ok, this.message);

  final bool ok;
  final String message;
}

const allowedRideTransitions = {
  'scheduled': ['searching', 'cancelled'],
  'requested': ['searching', 'cancelled'],
  'searching': ['accepted', 'cancelled'],
  'accepted': ['driver_arriving', 'cancelled'],
  'driver_arriving': ['arrived'],
  'arrived': ['in_progress'],
  'in_progress': ['completed'],
  'completed': <String>[],
  'cancelled': <String>[],
};

double calculateHaversineDistance({
  required double startLatitude,
  required double startLongitude,
  required double endLatitude,
  required double endLongitude,
}) {
  const earthKm = 6371.0;
  double radians(double value) => value * pi / 180;
  final dLat = radians(endLatitude - startLatitude);
  final dLng = radians(endLongitude - startLongitude);
  final lat1 = radians(startLatitude);
  final lat2 = radians(endLatitude);
  final h =
      pow(sin(dLat / 2), 2) + cos(lat1) * cos(lat2) * pow(sin(dLng / 2), 2);
  return double.parse((2 * earthKm * asin(sqrt(h))).toStringAsFixed(2));
}

Duration estimateTripDuration(double distanceKm, {double speedKph = 24}) {
  final minutes = max(5, ((max(distanceKm, 0.6) / speedKph) * 60 + 4).ceil());
  return Duration(minutes: minutes);
}

double estimateFareTotal({
  required double distanceKm,
  required int durationMinutes,
  int availableDrivers = 2,
}) {
  const baseFare = 4.5;
  final distanceFare = max(distanceKm, 0.6) * 1.85;
  final timeFare = max(durationMinutes, 5) * 0.32;
  const serviceFee = 1.75;
  final surge = availableDrivers < 2 ? 1.18 : 1.0;
  return double.parse(
    max(
      8,
      (baseFare + distanceFare + timeFare + serviceFee) * surge,
    ).toStringAsFixed(2),
  );
}

RideTransition validateRideTransition(String from, String to) {
  final allowed = allowedRideTransitions[from] ?? const <String>[];
  if (allowed.contains(to)) return const RideTransition(true, 'OK');
  return RideTransition(false, 'Cannot move ride from $from to $to.');
}
