import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../../shared/models/models.dart';
import '../../shared/utils/ride_math.dart';

class RoadRouteResult {
  const RoadRouteResult({
    required this.points,
    required this.distanceKm,
    required this.durationMinutes,
    required this.usedRoadRouting,
  });

  final List<LocationPoint> points;
  final double distanceKm;
  final int durationMinutes;
  final bool usedRoadRouting;
}

class RoutePlanningService {
  RoutePlanningService({http.Client? httpClient})
    : _http = httpClient ?? http.Client();

  final http.Client _http;

  Future<RoadRouteResult> drivingRoute(
    LocationPoint start,
    LocationPoint end,
  ) => drivingRouteThrough([start, end]);

  Future<RoadRouteResult> drivingRouteThrough(List<LocationPoint> stops) async {
    if (stops.length < 2) {
      return const RoadRouteResult(
        points: [],
        distanceKm: 0,
        durationMinutes: 0,
        usedRoadRouting: false,
      );
    }
    final localRoute = await _localBackendRoute(stops);
    if (localRoute != null) return localRoute;
    final distance = _routeDistanceKm(stops);
    return RoadRouteResult(
      points: stops,
      distanceKm: distance,
      durationMinutes: estimateTripDuration(distance).inMinutes,
      usedRoadRouting: false,
    );
  }

  void dispose() {
    _http.close();
  }

  Future<RoadRouteResult?> _localBackendRoute(List<LocationPoint> stops) async {
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/route/driving');
      final start = stops.first;
      final end = stops.last;
      final response = await _http
          .post(
            uri,
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode({
              'startLatitude': start.latitude,
              'startLongitude': start.longitude,
              'endLatitude': end.latitude,
              'endLongitude': end.longitude,
              'waypoints': stops
                  .skip(1)
                  .take(stops.length - 2)
                  .map(
                    (point) => {
                      'latitude': point.latitude,
                      'longitude': point.longitude,
                    },
                  )
                  .toList(),
            }),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode >= 400) return null;
      final payload = jsonDecode(response.body) as Map<String, dynamic>;
      final data = payload['data'];
      if (payload['success'] != true || data is! Map) return null;
      final pointsPayload = data['points'];
      if (pointsPayload is! List || pointsPayload.length < 2) return null;
      final points = <LocationPoint>[];
      for (final item in pointsPayload) {
        if (item is! Map) continue;
        final latitude = (item['latitude'] as num?)?.toDouble();
        final longitude = (item['longitude'] as num?)?.toDouble();
        if (latitude == null || longitude == null) continue;
        points.add(
          LocationPoint(
            address: 'Offline road route point',
            latitude: latitude,
            longitude: longitude,
          ),
        );
      }
      if (points.length < 2) return null;
      return RoadRouteResult(
        points: points,
        distanceKm:
            (data['distanceKm'] as num?)?.toDouble() ??
            _routeDistanceKm(points),
        durationMinutes:
            (data['durationMinutes'] as num?)?.toInt() ??
            estimateTripDuration(_routeDistanceKm(points)).inMinutes,
        usedRoadRouting: true,
      );
    } catch (_) {
      return null;
    }
  }

  double _routeDistanceKm(List<LocationPoint> points) {
    var distance = 0.0;
    for (var index = 1; index < points.length; index += 1) {
      distance += calculateHaversineDistance(
        startLatitude: points[index - 1].latitude,
        startLongitude: points[index - 1].longitude,
        endLatitude: points[index].latitude,
        endLongitude: points[index].longitude,
      );
    }
    return double.parse(distance.toStringAsFixed(2));
  }
}
