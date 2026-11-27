import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart' hide Path;

import '../../../core/config/app_config.dart';
import '../../../core/location/route_planning_service.dart';
import '../../../shared/models/models.dart';
import '../../../shared/theme/app_theme.dart';
import '../../../shared/utils/ride_math.dart';

String get _tileUrlTemplate {
  if (AppConfig.mapTileUrlTemplate.trim().isNotEmpty) {
    return AppConfig.mapTileUrlTemplate;
  }
  final base = AppConfig.apiBaseUrl.endsWith('/')
      ? AppConfig.apiBaseUrl.substring(0, AppConfig.apiBaseUrl.length - 1)
      : AppConfig.apiBaseUrl;
  return '$base/map/tiles/{z}/{x}/{y}{r}.png';
}

String get _referenceTileUrlTemplate =>
    AppConfig.mapReferenceTileUrlTemplate.trim();

class RouteResult {
  const RouteResult({
    required this.distanceKm,
    required this.duration,
    required this.polyline,
  });

  final double distanceKm;
  final Duration duration;
  final List<LocationPoint> polyline;
}

abstract class MapAdapter {
  Widget buildMap({
    LocationPoint? pickup,
    LocationPoint? destination,
    List<LocationPoint> waypoints = const [],
    LocationPoint? driver,
    LocationPoint? currentLocation,
    LocationPoint? serviceCenter,
    Ride? ride,
    bool fullBleed = false,
    bool compact = false,
    ValueChanged<LocationPoint>? onMapTap,
    String? tapTargetLabel,
    LocationPoint? focusLocation,
  });

  Future<LocationPoint?> getCurrentLocation();
  Future<RouteResult> calculateRoute(
    LocationPoint pickup,
    LocationPoint destination,
  );
}

class ServiceMapAdapter implements MapAdapter {
  const ServiceMapAdapter();

  @override
  Widget buildMap({
    LocationPoint? pickup,
    LocationPoint? destination,
    List<LocationPoint> waypoints = const [],
    LocationPoint? driver,
    LocationPoint? currentLocation,
    LocationPoint? serviceCenter,
    Ride? ride,
    bool fullBleed = false,
    bool compact = false,
    ValueChanged<LocationPoint>? onMapTap,
    String? tapTargetLabel,
    LocationPoint? focusLocation,
  }) {
    final ridePickup = ride == null
        ? pickup
        : LocationPoint(
            address: ride.pickupAddress,
            latitude: ride.pickupLatitude,
            longitude: ride.pickupLongitude,
          );
    final rideDestination = ride == null
        ? destination
        : LocationPoint(
            address: ride.destinationAddress,
            latitude: ride.destinationLatitude,
            longitude: ride.destinationLongitude,
          );
    final rideWaypoints = ride == null ? waypoints : ride.waypoints;
    final profile = ride?.driverProfile;
    final rideDriver = profile == null || ride?.hasConfirmedDriver != true
        ? driver
        : LocationPoint(
            address: ride?.driver?.name ?? 'Driver',
            latitude: profile.currentLatitude,
            longitude: profile.currentLongitude,
          );

    return RideMap(
      pickup: ridePickup,
      destination: rideDestination,
      waypoints: rideWaypoints,
      driver: rideDriver,
      currentLocation: currentLocation,
      serviceCenter: serviceCenter,
      rideStatus: ride?.status,
      fullBleed: fullBleed,
      compact: compact,
      onMapTap: onMapTap,
      tapTargetLabel: tapTargetLabel,
      focusLocation: focusLocation,
    );
  }

  @override
  Future<RouteResult> calculateRoute(
    LocationPoint pickup,
    LocationPoint destination,
  ) async {
    final distance = calculateHaversineDistance(
      startLatitude: pickup.latitude,
      startLongitude: pickup.longitude,
      endLatitude: destination.latitude,
      endLongitude: destination.longitude,
    );
    return RouteResult(
      distanceKm: distance,
      duration: estimateTripDuration(distance),
      polyline: [pickup, destination],
    );
  }

  @override
  Future<LocationPoint?> getCurrentLocation() async {
    return const LocationPoint(
      address: 'Downtown Los Angeles, CA',
      latitude: 34.0522,
      longitude: -118.2437,
    );
  }
}

class RideMap extends StatefulWidget {
  const RideMap({
    this.pickup,
    this.destination,
    this.waypoints = const [],
    this.driver,
    this.currentLocation,
    this.serviceCenter,
    this.rideStatus,
    this.fullBleed = false,
    this.compact = false,
    this.onMapTap,
    this.tapTargetLabel,
    this.focusLocation,
    super.key,
  });

  final LocationPoint? pickup;
  final LocationPoint? destination;
  final List<LocationPoint> waypoints;
  final LocationPoint? driver;
  final LocationPoint? currentLocation;
  final LocationPoint? serviceCenter;
  final String? rideStatus;
  final bool fullBleed;
  final bool compact;
  final ValueChanged<LocationPoint>? onMapTap;
  final String? tapTargetLabel;
  final LocationPoint? focusLocation;

  @override
  State<RideMap> createState() => _RideMapState();
}

class _RideMapState extends State<RideMap> with SingleTickerProviderStateMixin {
  static const _defaultCenter = LatLng(39.8283, -98.5795);
  static const _localVectorMaxZoom = 18.5;
  static const _pmTilesNativeMaxZoom = 15.0;
  static const _rasterNativeMaxZoom = 19.0;

  final _controller = MapController();
  final _routePlanner = RoutePlanningService();
  final _tileResetController = StreamController<void>.broadcast();
  late final AnimationController _driverAnimationController;
  late final MapOptions _mapOptions;
  late final bool _localPmTilesAvailable;
  List<LatLng> _routePoints = const [];
  LatLng? _displayedDriverPoint;
  LatLng? _driverAnimationStart;
  LatLng? _driverAnimationTarget;
  List<LatLng> _driverAnimationPath = const [];
  double _driverHeadingRadians = 0;
  bool _isPlanningRoute = false;
  bool _usingRoadRoute = false;
  int _routeGeneration = 0;
  bool _mapReady = false;
  bool _userMovedMap = false;
  bool _tileLoadFailed = false;
  final int _tileRetryGeneration = 0;

  @override
  void initState() {
    super.initState();
    _localPmTilesAvailable = false;
    _displayedDriverPoint =
        widget.driver == null ? null : _latLng(widget.driver!);
    _driverAnimationController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2800),
    )..addListener(_tickDriverAnimation);
    _mapOptions = MapOptions(
      initialCenter: _initialCenter(),
      initialZoom: widget.currentLocation == null ? 12.5 : 15.0,
      minZoom: 4,
      maxZoom:
          _localPmTilesAvailable ? _localVectorMaxZoom : _rasterNativeMaxZoom,
      backgroundColor: const Color(0xFFEAF0F6),
      interactionOptions: InteractionOptions(
        flags: widget.compact
            ? InteractiveFlag.drag |
                InteractiveFlag.flingAnimation |
                InteractiveFlag.pinchMove |
                InteractiveFlag.pinchZoom |
                InteractiveFlag.doubleTapZoom
            : InteractiveFlag.drag |
                InteractiveFlag.flingAnimation |
                InteractiveFlag.pinchMove |
                InteractiveFlag.pinchZoom |
                InteractiveFlag.scrollWheelZoom |
                InteractiveFlag.doubleTapZoom |
                InteractiveFlag.doubleTapDragZoom,
      ),
      onMapReady: () {
        _mapReady = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted) return;
          _applyRouteCamera(_routePoints);
        });
      },
      onTap: (_, point) {
        widget.onMapTap?.call(
          LocationPoint(
            address:
                'Dropped pin ${point.latitude.toStringAsFixed(5)}, ${point.longitude.toStringAsFixed(5)}',
            latitude: point.latitude,
            longitude: point.longitude,
          ),
        );
      },
      onPositionChanged: (_, hasGesture) {
        if (hasGesture) _userMovedMap = true;
      },
    );
    _refreshRoadRoute();
  }

  @override
  void didUpdateWidget(covariant RideMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    _syncDriverAnimation(oldWidget.driver, widget.driver);
    final oldCurrent = oldWidget.currentLocation;
    final newCurrent = widget.currentLocation;
    if (!_userMovedMap &&
        _mapReady &&
        oldCurrent == null &&
        newCurrent != null) {
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => _moveTo(_latLng(newCurrent), 15, markUserMoved: false),
      );
    }
    if (_routeKey(oldWidget) != _routeKey(widget)) {
      _resetTileRetries();
      _refreshRoadRoute();
    }
    if (_focusKey(oldWidget.focusLocation) != _focusKey(widget.focusLocation)) {
      _resetTileRetries();
      _focusSelectedLocation();
    }
  }

  @override
  void dispose() {
    _driverAnimationController.dispose();
    _routePlanner.dispose();
    _tileResetController.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final map = ClipRRect(
      borderRadius: BorderRadius.circular(widget.fullBleed ? 0 : 24),
      child: Stack(
        children: [
          Positioned.fill(
            child: FlutterMap(
              mapController: _controller,
              options: _mapOptions,
              children: [
                _BasemapLayer(
                  tileRetryGeneration: _tileRetryGeneration,
                  tileResetStream: _tileResetController.stream,
                  onTileLoadFailed: _markTileLoadFailed,
                ),
                if (_referenceTileUrlTemplate.isNotEmpty)
                  TileLayer(
                    key: const ValueKey('reference-tiles'),
                    urlTemplate: _referenceTileUrlTemplate,
                    userAgentPackageName: 'com.opendriver.desktop',
                    retinaMode: RetinaMode.isHighDensity(context),
                    maxNativeZoom: _RideMapState._rasterNativeMaxZoom.toInt(),
                    keepBuffer: 4,
                    panBuffer: 2,
                    tileDisplay: const TileDisplay.instantaneous(),
                    evictErrorTileStrategy: EvictErrorTileStrategy.none,
                    reset: _tileResetController.stream,
                  ),
                if (_routePoints.length >= 2)
                  PolylineLayer(
                    polylines: [
                      Polyline(
                        points: _routePoints,
                        color: AppColors.accent,
                        borderColor: Colors.white,
                        borderStrokeWidth: 8,
                        strokeWidth: 5,
                      ),
                    ],
                  ),
                MarkerLayer(markers: _markers()),
              ],
            ),
          ),
          if (!widget.fullBleed)
            Positioned(
              left: 16,
              top: 16,
              child: _MapToolbar(
                rideStatus: widget.rideStatus,
                compact: widget.compact,
                tapTargetLabel: widget.tapTargetLabel,
                routeModeLabel: _isPlanningRoute
                    ? 'planning road route'
                    : _usingRoadRoute
                        ? 'road route'
                        : _tileLoadFailed
                            ? 'local map fallback'
                            : 'fallback route',
                onCurrent: widget.currentLocation == null
                    ? null
                    : () => _moveTo(_latLng(widget.currentLocation!), 15.5),
                onServiceCity: () => _moveTo(_serviceCenter(), 11.5),
                onZoomIn: () => _zoomBy(1),
                onZoomOut: () => _zoomBy(-1),
              ),
            ),
        ],
      ),
    );

    if (widget.fullBleed) {
      return Positioned.fill(child: map);
    }

    final width = MediaQuery.sizeOf(context).width;
    final height = widget.compact
        ? (width >= 900 ? 260.0 : 220.0)
        : (width >= 900 ? 520.0 : 380.0);
    return SizedBox(height: height, child: map);
  }

  LatLng _initialCenter() {
    if (_isDriverNavigationMode && widget.driver != null) {
      return _latLng(widget.driver!);
    }
    if (widget.currentLocation != null) return _latLng(widget.currentLocation!);
    if (widget.pickup != null && widget.destination != null) {
      return LatLng(
        (widget.pickup!.latitude + widget.destination!.latitude) / 2,
        (widget.pickup!.longitude + widget.destination!.longitude) / 2,
      );
    }
    if (widget.pickup != null) return _latLng(widget.pickup!);
    if (widget.destination != null) return _latLng(widget.destination!);
    if (widget.driver != null) return _latLng(widget.driver!);
    return _serviceCenter();
  }

  LatLng _serviceCenter() {
    final center = widget.serviceCenter;
    return center == null ? _defaultCenter : _latLng(center);
  }

  List<Marker> _markers() {
    final driverPoint = _displayedDriverPoint ??
        (widget.driver == null ? null : _latLng(widget.driver!));
    final currentLocationOverlapsDriver = widget.currentLocation != null &&
        widget.driver != null &&
        _sameMapPoint(widget.currentLocation!, widget.driver!);
    return [
      if (widget.currentLocation != null && !currentLocationOverlapsDriver)
        Marker(
          point: _latLng(widget.currentLocation!),
          width: 64,
          height: 64,
          child: const _CurrentLocationMarker(),
        ),
      if (widget.pickup != null)
        Marker(
          point: _latLng(widget.pickup!),
          width: 70,
          height: 70,
          child: const _MapMarker(
            label: 'P',
            title: 'Pickup',
            color: AppColors.accent,
            icon: Icons.trip_origin,
          ),
        ),
      for (var index = 0; index < widget.waypoints.length; index += 1)
        Marker(
          point: _latLng(widget.waypoints[index]),
          width: 70,
          height: 70,
          child: _MapMarker(
            label: '${index + 1}',
            title: 'Stop ${index + 1}',
            color: const Color(0xFF7C3AED),
            icon: Icons.add_location_alt,
          ),
        ),
      if (widget.destination != null)
        Marker(
          point: _latLng(widget.destination!),
          width: 70,
          height: 70,
          child: const _MapMarker(
            label: 'D',
            title: 'Destination',
            color: AppColors.danger,
            icon: Icons.flag,
          ),
        ),
      if (driverPoint != null)
        Marker(
          point: driverPoint,
          width: 58,
          height: 58,
          child: _DriverCarMarker(headingRadians: _driverHeadingRadians),
        ),
    ];
  }

  LatLng _latLng(LocationPoint point) =>
      LatLng(point.latitude, point.longitude);

  bool _sameMapPoint(LocationPoint a, LocationPoint b) {
    return (a.latitude - b.latitude).abs() < 0.00001 &&
        (a.longitude - b.longitude).abs() < 0.00001;
  }

  bool get _isDriverNavigationMode {
    return widget.driver != null &&
        ['driver_arriving', 'in_progress'].contains(widget.rideStatus);
  }

  LatLng? get _driverCameraPoint {
    return _displayedDriverPoint ??
        (widget.driver == null ? null : _latLng(widget.driver!));
  }

  String _routeKey(RideMap widget) {
    final stops = _routeStopsFor(widget);
    if (stops == null) return 'none';
    if (widget.driver != null &&
        [
          'accepted',
          'driver_arriving',
          'arrived',
        ].contains(widget.rideStatus)) {
      return [
        'driver_to_pickup',
        widget.rideStatus ?? 'preview',
        stops.last.latitude.toStringAsFixed(5),
        stops.last.longitude.toStringAsFixed(5),
      ].join('|');
    }
    return [
      widget.rideStatus ?? 'preview',
      for (final stop in stops)
        '${stop.latitude.toStringAsFixed(5)},${stop.longitude.toStringAsFixed(5)}',
    ].join('|');
  }

  String _focusKey(LocationPoint? point) {
    if (point == null) return 'none';
    return '${point.latitude.toStringAsFixed(5)}|${point.longitude.toStringAsFixed(5)}';
  }

  List<LocationPoint>? _routeStopsFor(RideMap widget) {
    final pickup = widget.pickup;
    final destination = widget.destination;
    if (pickup == null || destination == null) return null;
    final driver = widget.driver;
    if (driver != null &&
        [
          'accepted',
          'driver_arriving',
          'arrived',
        ].contains(widget.rideStatus)) {
      return [driver, pickup];
    }
    return [pickup, ...widget.waypoints, destination];
  }

  Future<void> _refreshRoadRoute() async {
    final stops = _routeStopsFor(widget);
    final generation = ++_routeGeneration;
    if (stops == null || stops.length < 2) {
      setState(() {
        _routePoints = const [];
        _isPlanningRoute = false;
        _usingRoadRoute = false;
      });
      return;
    }

    setState(() {
      _routePoints = const [];
      _isPlanningRoute = true;
      _usingRoadRoute = false;
    });
    _applyRouteCamera(stops.map(_latLng).toList(growable: false));

    final result = await _routePlanner.drivingRouteThrough(stops);
    if (!mounted || generation != _routeGeneration) return;
    setState(() {
      _routePoints = result.points.map(_latLng).toList(growable: false);
      _isPlanningRoute = false;
      _usingRoadRoute = result.usedRoadRouting;
    });
    _applyRouteCamera(_routePoints);
  }

  void _focusSelectedLocation() {
    if (_isDriverNavigationMode) {
      _lockCameraToDriver(initial: true);
      return;
    }
    final focus = widget.focusLocation;
    if (focus == null || !_mapReady) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _controller.move(_latLng(focus), 15.5);
    });
  }

  void _moveTo(LatLng point, double zoom, {bool markUserMoved = true}) {
    if (!_mapReady) return;
    if (markUserMoved) _userMovedMap = true;
    _controller.move(point, zoom);
  }

  void _zoomBy(double delta) {
    if (!_mapReady) return;
    final maxZoom =
        _localPmTilesAvailable ? _localVectorMaxZoom : _rasterNativeMaxZoom;
    final zoom =
        (_controller.camera.zoom + delta).clamp(4.0, maxZoom).toDouble();
    _userMovedMap = true;
    _controller.move(_controller.camera.center, zoom);
  }

  void _syncDriverAnimation(
    LocationPoint? oldDriver,
    LocationPoint? newDriver,
  ) {
    if (newDriver == null) {
      _driverAnimationController.stop();
      _displayedDriverPoint = null;
      _driverAnimationStart = null;
      _driverAnimationTarget = null;
      _driverAnimationPath = const [];
      return;
    }

    final next = _latLng(newDriver);
    if (_displayedDriverPoint == null || oldDriver == null) {
      _displayedDriverPoint = next;
      _driverAnimationStart = next;
      _driverAnimationTarget = next;
      _driverAnimationPath = [next];
      return;
    }

    final current = _displayedDriverPoint!;
    if ((current.latitude - next.latitude).abs() < 0.000005 &&
        (current.longitude - next.longitude).abs() < 0.000005) {
      return;
    }

    final path = _routeAlignedDriverPath(current, next);
    _driverHeadingRadians = _bearingRadians(path.first, path.last);
    _driverAnimationStart = path.first;
    _driverAnimationTarget = path.last;
    _driverAnimationPath = path;
    _driverAnimationController.forward(from: 0);
  }

  double _bearingRadians(LatLng from, LatLng to) {
    final lat1 = from.latitude * math.pi / 180;
    final lat2 = to.latitude * math.pi / 180;
    final deltaLongitude = (to.longitude - from.longitude) * math.pi / 180;
    final y = math.sin(deltaLongitude) * math.cos(lat2);
    final x = math.cos(lat1) * math.sin(lat2) -
        math.sin(lat1) * math.cos(lat2) * math.cos(deltaLongitude);
    return math.atan2(y, x);
  }

  void _tickDriverAnimation() {
    final start = _driverAnimationStart;
    final target = _driverAnimationTarget;
    if (start == null || target == null || !mounted) return;
    final eased = Curves.easeInOutCubic.transform(
      _driverAnimationController.value,
    );
    final path = _driverAnimationPath.length >= 2
        ? _driverAnimationPath
        : <LatLng>[start, target];
    final point = _pointAlongRoute(path, eased);
    final lookAhead = _pointAlongRoute(path, math.min(1, eased + 0.015));
    setState(() {
      _displayedDriverPoint = point;
      if (_distanceKm(point, lookAhead) > 0.001) {
        _driverHeadingRadians = _bearingRadians(point, lookAhead);
      }
    });
    if (_isDriverNavigationMode) _lockCameraToDriver();
  }

  List<LatLng> _routeAlignedDriverPath(LatLng start, LatLng end) {
    if (_routePoints.length < 2) return [start, end];
    final startProjection = _nearestRouteProjection(start);
    final endProjection = _nearestRouteProjection(end);
    if (startProjection == null || endProjection == null) return [start, end];

    if (endProjection.distanceKm >= startProjection.distanceKm) {
      return _routeSlice(startProjection, endProjection);
    }
    return _routeSlice(endProjection, startProjection).reversed.toList();
  }

  List<LatLng> _routeSlice(_RouteProjection start, _RouteProjection end) {
    final points = <LatLng>[start.point];
    if (start.segmentIndex == end.segmentIndex) {
      points.add(end.point);
      return _dedupeRoutePoints(points);
    }

    for (var index = start.segmentIndex + 1;
        index <= end.segmentIndex && index < _routePoints.length;
        index += 1) {
      points.add(_routePoints[index]);
    }
    points.add(end.point);
    return _dedupeRoutePoints(points);
  }

  List<LatLng> _dedupeRoutePoints(List<LatLng> points) {
    final deduped = <LatLng>[];
    for (final point in points) {
      if (deduped.isEmpty || _distanceKm(deduped.last, point) > 0.001) {
        deduped.add(point);
      }
    }
    return deduped.length >= 2 ? deduped : points;
  }

  _RouteProjection? _nearestRouteProjection(LatLng point) {
    _RouteProjection? best;
    var traveledKm = 0.0;
    for (var index = 1; index < _routePoints.length; index += 1) {
      final start = _routePoints[index - 1];
      final end = _routePoints[index];
      final segmentKm = _distanceKm(start, end);
      final projection = _projectPointOnSegment(point, start, end);
      final distanceFromPointKm = _distanceKm(point, projection.point);
      final candidate = _RouteProjection(
        point: projection.point,
        segmentIndex: index - 1,
        distanceKm: traveledKm + segmentKm * projection.ratio,
        distanceFromPointKm: distanceFromPointKm,
      );
      if (best == null ||
          candidate.distanceFromPointKm < best.distanceFromPointKm) {
        best = candidate;
      }
      traveledKm += segmentKm;
    }
    return best;
  }

  _SegmentProjection _projectPointOnSegment(
    LatLng point,
    LatLng start,
    LatLng end,
  ) {
    const latitudeScale = 111.320;
    final longitudeScale = 111.320 *
        math.cos(((start.latitude + end.latitude) / 2) * math.pi / 180);
    final px = point.longitude * longitudeScale;
    final py = point.latitude * latitudeScale;
    final sx = start.longitude * longitudeScale;
    final sy = start.latitude * latitudeScale;
    final ex = end.longitude * longitudeScale;
    final ey = end.latitude * latitudeScale;
    final dx = ex - sx;
    final dy = ey - sy;
    final lengthSquared = dx * dx + dy * dy;
    final ratio = lengthSquared <= 0
        ? 0.0
        : (((px - sx) * dx + (py - sy) * dy) / lengthSquared)
            .clamp(0.0, 1.0)
            .toDouble();
    return _SegmentProjection(
      point: LatLng(
        start.latitude + (end.latitude - start.latitude) * ratio,
        start.longitude + (end.longitude - start.longitude) * ratio,
      ),
      ratio: ratio,
    );
  }

  LatLng _pointAlongRoute(List<LatLng> points, double ratio) {
    if (points.length <= 1) return points.first;
    final targetRatio = ratio.clamp(0.0, 1.0).toDouble();
    final totalKm = _routeDistanceKm(points);
    if (totalKm <= 0) return points.last;
    var traveledKm = 0.0;
    final targetKm = totalKm * targetRatio;
    for (var index = 1; index < points.length; index += 1) {
      final start = points[index - 1];
      final end = points[index];
      final segmentKm = _distanceKm(start, end);
      if (traveledKm + segmentKm >= targetKm) {
        final segmentRatio =
            segmentKm <= 0 ? 1.0 : (targetKm - traveledKm) / segmentKm;
        return LatLng(
          start.latitude + (end.latitude - start.latitude) * segmentRatio,
          start.longitude + (end.longitude - start.longitude) * segmentRatio,
        );
      }
      traveledKm += segmentKm;
    }
    return points.last;
  }

  double _routeDistanceKm(List<LatLng> points) {
    var distance = 0.0;
    for (var index = 1; index < points.length; index += 1) {
      distance += _distanceKm(points[index - 1], points[index]);
    }
    return distance;
  }

  double _distanceKm(LatLng start, LatLng end) {
    return calculateHaversineDistance(
      startLatitude: start.latitude,
      startLongitude: start.longitude,
      endLatitude: end.latitude,
      endLongitude: end.longitude,
    );
  }

  void _applyRouteCamera(List<LatLng> points) {
    if (!_mapReady) return;
    if (_isDriverNavigationMode) {
      _lockCameraToDriver(initial: true);
      return;
    }
    _fitRouteToView(points);
  }

  void _lockCameraToDriver({bool initial = false}) {
    if (!_mapReady) return;
    final driver = _driverCameraPoint;
    if (driver == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_mapReady) return;
      final currentZoom = _controller.camera.zoom;
      final zoom = initial
          ? _navigationZoom()
          : currentZoom.clamp(12.0, 18.0).toDouble();
      _controller.move(driver, zoom);
    });
  }

  double _navigationZoom() {
    final distance = _routeDistanceKm(_routePoints);
    if (distance <= 1.2) return widget.compact ? 15.8 : 16.2;
    if (distance <= 4) return widget.compact ? 14.9 : 15.4;
    if (distance <= 9) return widget.compact ? 14.1 : 14.7;
    return widget.compact ? 13.4 : 14.0;
  }

  void _fitRouteToView(List<LatLng> points) {
    if (!_mapReady || points.length < 2) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_mapReady || points.length < 2) return;
      final size = MediaQuery.sizeOf(context);
      final isDesktop = widget.fullBleed && size.width >= 900;
      final padding = widget.compact
          ? const EdgeInsets.fromLTRB(20, 104, 20, 48)
          : isDesktop
              ? const EdgeInsets.fromLTRB(520, 130, 560, 90)
              : const EdgeInsets.fromLTRB(28, 120, 28, 160);
      _controller.fitCamera(
        CameraFit.coordinates(
          coordinates: points,
          padding: padding,
          maxZoom: _localPmTilesAvailable
              ? math.max(_pmTilesNativeMaxZoom, _localVectorMaxZoom - 1)
              : (widget.compact ? 18.0 : 18.5),
          minZoom: 10,
        ),
      );
      _resetTilesAfterCameraMove();
      _nudgeCameraAfterFit();
    });
  }

  void _resetTilesAfterCameraMove() {
    if (_tileResetController.isClosed) return;
    _tileResetController.add(null);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && !_tileResetController.isClosed) {
        _tileResetController.add(null);
      }
    });
    Future<void>.delayed(const Duration(milliseconds: 120), () {
      if (mounted && !_tileResetController.isClosed) {
        _tileResetController.add(null);
      }
    });
  }

  void _nudgeCameraAfterFit() {
    Future<void>.delayed(const Duration(milliseconds: 80), () {
      if (!mounted || !_mapReady) return;
      final camera = _controller.camera;
      final minZoom = _mapOptions.minZoom ?? 4.0;
      final maxZoom = _mapOptions.maxZoom ?? _rasterNativeMaxZoom;
      final originalZoom = camera.zoom.clamp(minZoom, maxZoom).toDouble();
      final delta = originalZoom + 0.0005 <= maxZoom ? 0.0005 : -0.0005;
      final nudgedZoom =
          (originalZoom + delta).clamp(minZoom, maxZoom).toDouble();
      _controller.move(camera.center, nudgedZoom, id: 'opendriver-route-nudge');
      _resetTilesAfterCameraMove();
      Future<void>.delayed(const Duration(milliseconds: 40), () {
        if (!mounted || !_mapReady) return;
        _controller.move(
          _controller.camera.center,
          originalZoom,
          id: 'opendriver-route-nudge-back',
        );
        _resetTilesAfterCameraMove();
      });
    });
  }

  void _resetTileRetries() {
    _tileLoadFailed = false;
  }

  void _markTileLoadFailed() {
    if (!mounted) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      setState(() {
        _tileLoadFailed = true;
      });
    });
  }
}

class _BasemapLayer extends StatelessWidget {
  const _BasemapLayer({
    required this.tileRetryGeneration,
    required this.tileResetStream,
    required this.onTileLoadFailed,
  });

  final int tileRetryGeneration;
  final Stream<void> tileResetStream;
  final VoidCallback onTileLoadFailed;

  @override
  Widget build(BuildContext context) {
    return _RasterBasemapLayer(
      tileRetryGeneration: tileRetryGeneration,
      tileResetStream: tileResetStream,
      onTileLoadFailed: onTileLoadFailed,
    );
  }
}

class _RasterBasemapLayer extends StatelessWidget {
  const _RasterBasemapLayer({
    required this.tileRetryGeneration,
    required this.tileResetStream,
    required this.onTileLoadFailed,
  });

  final int tileRetryGeneration;
  final Stream<void> tileResetStream;
  final VoidCallback onTileLoadFailed;

  @override
  Widget build(BuildContext context) {
    return TileLayer(
      key: const ValueKey('local-raster-tiles'),
      urlTemplate: _tileUrlTemplate,
      userAgentPackageName: 'com.opendriver.desktop',
      retinaMode: RetinaMode.isHighDensity(context),
      maxNativeZoom: _RideMapState._rasterNativeMaxZoom.toInt(),
      keepBuffer: 4,
      panBuffer: 2,
      tileDisplay: const TileDisplay.instantaneous(),
      evictErrorTileStrategy: EvictErrorTileStrategy.none,
      reset: tileResetStream,
      errorTileCallback: (_, __, ___) => onTileLoadFailed(),
    );
  }
}

class _RouteProjection {
  const _RouteProjection({
    required this.point,
    required this.segmentIndex,
    required this.distanceKm,
    required this.distanceFromPointKm,
  });

  final LatLng point;
  final int segmentIndex;
  final double distanceKm;
  final double distanceFromPointKm;
}

class _SegmentProjection {
  const _SegmentProjection({required this.point, required this.ratio});

  final LatLng point;
  final double ratio;
}

class _MapToolbar extends StatelessWidget {
  const _MapToolbar({
    required this.onServiceCity,
    required this.onZoomIn,
    required this.onZoomOut,
    required this.compact,
    this.onCurrent,
    this.rideStatus,
    this.tapTargetLabel,
    this.routeModeLabel,
  });

  final VoidCallback? onCurrent;
  final VoidCallback onServiceCity;
  final VoidCallback onZoomIn;
  final VoidCallback onZoomOut;
  final bool compact;
  final String? rideStatus;
  final String? tapTargetLabel;
  final String? routeModeLabel;

  @override
  Widget build(BuildContext context) {
    final buttonStyle = IconButton.styleFrom(
      minimumSize: Size.square(compact ? 36 : 40),
      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      padding: EdgeInsets.all(compact ? 6 : 8),
    );
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(18),
        boxShadow: const [
          BoxShadow(
            color: Color(0x22000000),
            blurRadius: 14,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.map, color: AppColors.accent),
            const SizedBox(width: 8),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  rideStatus == null
                      ? 'Live map'
                      : rideStatus!.replaceAll('_', ' '),
                  style: const TextStyle(fontWeight: FontWeight.w900),
                ),
                if (tapTargetLabel != null)
                  Text(
                    'Tap map to set $tapTargetLabel',
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.muted,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                if (routeModeLabel != null)
                  Text(
                    routeModeLabel!,
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.muted,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
              ],
            ),
            const SizedBox(width: 8),
            IconButton(
              style: buttonStyle,
              tooltip: 'My location',
              onPressed: onCurrent,
              icon: const Icon(Icons.near_me),
            ),
            IconButton(
              style: buttonStyle,
              tooltip: 'Service city',
              onPressed: onServiceCity,
              icon: const Icon(Icons.fit_screen),
            ),
            IconButton(
              style: buttonStyle,
              tooltip: 'Zoom in',
              onPressed: onZoomIn,
              icon: const Icon(Icons.add),
            ),
            IconButton(
              style: buttonStyle,
              tooltip: 'Zoom out',
              onPressed: onZoomOut,
              icon: const Icon(Icons.remove),
            ),
          ],
        ),
      ),
    );
  }
}

class _MapMarker extends StatelessWidget {
  const _MapMarker({
    required this.label,
    required this.title,
    required this.color,
    required this.icon,
  });

  final String label;
  final String title;
  final Color color;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: title,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(18),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x33000000),
                  blurRadius: 10,
                  offset: Offset(0, 4),
                ),
              ],
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, color: Colors.white, size: 16),
                const SizedBox(width: 4),
                Text(
                  label,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ],
            ),
          ),
          Icon(Icons.arrow_drop_down, color: color, size: 28),
        ],
      ),
    );
  }
}

class _DriverCarMarker extends StatelessWidget {
  const _DriverCarMarker({required this.headingRadians});

  final double headingRadians;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: 'Driver',
      child: SizedBox(
        width: 58,
        height: 58,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Positioned(
              bottom: 10,
              child: Container(
                width: 30,
                height: 8,
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.20),
                  borderRadius: BorderRadius.circular(999),
                  boxShadow: const [
                    BoxShadow(
                      color: Color(0x33000000),
                      blurRadius: 8,
                      offset: Offset(0, 2),
                    ),
                  ],
                ),
              ),
            ),
            Transform.rotate(
              angle: headingRadians,
              child: const CustomPaint(
                size: Size(42, 42),
                painter: _TopDownCarPainter(),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TopDownCarPainter extends CustomPainter {
  const _TopDownCarPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final bodyPaint = Paint()..color = AppColors.ink;
    final glassPaint = Paint()..color = const Color(0xFFEAF7FF);
    final detailPaint = Paint()..color = Colors.white;
    final tirePaint = Paint()..color = const Color(0xFF050A16);

    final tireWidth = size.width * 0.13;
    final tireHeight = size.height * 0.22;
    for (final tire in [
      Rect.fromLTWH(
        size.width * 0.16,
        size.height * 0.24,
        tireWidth,
        tireHeight,
      ),
      Rect.fromLTWH(
        size.width * 0.71,
        size.height * 0.24,
        tireWidth,
        tireHeight,
      ),
      Rect.fromLTWH(
        size.width * 0.16,
        size.height * 0.58,
        tireWidth,
        tireHeight,
      ),
      Rect.fromLTWH(
        size.width * 0.71,
        size.height * 0.58,
        tireWidth,
        tireHeight,
      ),
    ]) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(tire, const Radius.circular(4)),
        tirePaint,
      );
    }

    final bodyPath = Path()
      ..moveTo(center.dx, size.height * 0.05)
      ..cubicTo(
        size.width * 0.78,
        size.height * 0.12,
        size.width * 0.78,
        size.height * 0.26,
        size.width * 0.75,
        size.height * 0.40,
      )
      ..lineTo(size.width * 0.72, size.height * 0.82)
      ..quadraticBezierTo(
        size.width * 0.70,
        size.height * 0.94,
        center.dx,
        size.height * 0.96,
      )
      ..quadraticBezierTo(
        size.width * 0.30,
        size.height * 0.94,
        size.width * 0.28,
        size.height * 0.82,
      )
      ..lineTo(size.width * 0.25, size.height * 0.40)
      ..cubicTo(
        size.width * 0.22,
        size.height * 0.26,
        size.width * 0.22,
        size.height * 0.12,
        center.dx,
        size.height * 0.05,
      )
      ..close();

    canvas.drawPath(bodyPath, Paint()..color = Colors.white);
    canvas.drawPath(bodyPath, bodyPaint);

    final windshield = RRect.fromRectAndRadius(
      Rect.fromCenter(
        center: Offset(center.dx, size.height * 0.31),
        width: size.width * 0.38,
        height: size.height * 0.20,
      ),
      const Radius.circular(6),
    );
    final rearWindow = RRect.fromRectAndRadius(
      Rect.fromCenter(
        center: Offset(center.dx, size.height * 0.68),
        width: size.width * 0.34,
        height: size.height * 0.18,
      ),
      const Radius.circular(6),
    );
    canvas.drawRRect(windshield, glassPaint);
    canvas.drawRRect(rearWindow, glassPaint);

    final hoodLine = Path()
      ..moveTo(size.width * 0.38, size.height * 0.17)
      ..quadraticBezierTo(
        center.dx,
        size.height * 0.12,
        size.width * 0.62,
        size.height * 0.17,
      );
    canvas.drawPath(
      hoodLine,
      Paint()
        ..color = Colors.white.withValues(alpha: 0.28)
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round,
    );

    canvas.drawCircle(
      Offset(size.width * 0.36, size.height * 0.10),
      2.2,
      detailPaint,
    );
    canvas.drawCircle(
      Offset(size.width * 0.64, size.height * 0.10),
      2.2,
      detailPaint,
    );
  }

  @override
  bool shouldRepaint(covariant _TopDownCarPainter oldDelegate) => false;
}

class _CurrentLocationMarker extends StatelessWidget {
  const _CurrentLocationMarker();

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: 'Your current location',
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: AppColors.current.withValues(alpha: 0.16),
              shape: BoxShape.circle,
            ),
          ),
          Container(
            width: 22,
            height: 22,
            decoration: BoxDecoration(
              color: AppColors.current,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white, width: 4),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x44000000),
                  blurRadius: 10,
                  offset: Offset(0, 3),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
…D