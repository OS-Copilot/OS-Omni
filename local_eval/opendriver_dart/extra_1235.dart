'import 'package:http/http.dart' as http;

import '../../shared/models/models.dart';

class CurrentLocationService {
  // Keep the app anchored to Silicon Valley instead of drifting with IP geolocation.
  CurrentLocationService({http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  // Retained for constructor compatibility in tests and callers that inject a client.
  // The fixed local location intentionally does not make network requests.
  // ignore: unused_field
  final http.Client _http;

  Future<LocationPoint> resolveCurrentLocation() async {
    return const LocationPoint(
      id: 'silicon_valley_default',
      cityId: 'sf_bay',
      address: 'University Avenue, Palo Alto, CA',
      latitude: 37.4477,
      longitude: -122.1619,
    );
  }
}
