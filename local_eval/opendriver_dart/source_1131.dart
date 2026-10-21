simport 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../storage/token_store.dart';

class ApiException implements Exception {
  const ApiException(this.code, this.message);

  final String code;
  final String message;

  @override
  String toString() => '$code: $message';
}

class ApiClient {
  ApiClient({required this.tokenStore, http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  static const _timeout = Duration(seconds: 15);

  final TokenStore tokenStore;
  final http.Client _http;

  Uri _uri(String path) => Uri.parse('${AppConfig.apiBaseUrl}$path');

  Future<Map<String, dynamic>> get(String path) => _request('GET', path);

  Future<Map<String, dynamic>> post(
    String path, [
    Map<String, dynamic>? body,
  ]) =>
      _request('POST', path, body);

  Future<Map<String, dynamic>> patch(
    String path, [
    Map<String, dynamic>? body,
  ]) =>
      _request('PATCH', path, body);

  Future<Map<String, dynamic>> delete(String path) => _request('DELETE', path);

  Future<Map<String, dynamic>> _request(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    final token = await tokenStore.readToken();
    final headers = <String, String>{
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
    final encoded = body == null ? null : jsonEncode(body);
    late http.Response response;
    try {
      if (method == 'GET') {
        response =
            await _http.get(_uri(path), headers: headers).timeout(_timeout);
      } else if (method == 'POST') {
        response = await _http
            .post(_uri(path), headers: headers, body: encoded)
            .timeout(_timeout);
      } else if (method == 'PATCH') {
        response = await _http
            .patch(_uri(path), headers: headers, body: encoded)
            .timeout(_timeout);
      } else if (method == 'DELETE') {
        response =
            await _http.delete(_uri(path), headers: headers).timeout(_timeout);
      } else {
        throw const ApiException(
          'UNSUPPORTED_METHOD',
          'Unsupported HTTP method.',
        );
      }
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException(
        'NETWORK_UNAVAILABLE',
        'Cannot reach opendriver right now. Check the backend URL and your connection.',
      );
    }

    final payload = _decodePayload(response);
    if (response.statusCode >= 400 || payload['success'] == false) {
      final error = payload['error'] as Map<String, dynamic>? ?? {};
      throw ApiException(
        error['code'] as String? ?? 'REQUEST_FAILED',
        error['message'] as String? ?? 'Request failed.',
      );
    }
    return payload['data'] as Map<String, dynamic>? ?? {};
  }

  Map<String, dynamic> _decodePayload(http.Response response) {
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map<String, dynamic>) return decoded;
    } catch (_) {
      // Fall through to a stable API exception below.
    }
    throw ApiException(
      'INVALID_SERVER_RESPONSE',
      response.statusCode >= 500
          ? 'opendriver server had a problem. Please try again.'
          : 'opendriver returned an unreadable response.',
    );
  }
}
r