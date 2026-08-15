import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../constants.dart';

class ApiException implements Exception {
  final int statusCode;
  final String? code;
  final String message;

  const ApiException({
    required this.statusCode,
    required this.message,
    this.code,
  });

  @override
  String toString() {
    final codeText = code == null ? '' : ' ($code)';
    return 'HTTP $statusCode$codeText: $message';
  }
}

class ApiClient {
  static http.Client _httpClient = http.Client();

  static http.Client get httpClient => _httpClient;

  @visibleForTesting
  static set httpClient(http.Client client) {
    _httpClient = client;
  }

  static Map<String, dynamic> _jsonUtf8(http.Response r) {
    final body = utf8.decode(r.bodyBytes);
    return json.decode(body) as Map<String, dynamic>;
  }

  static void _log(String message) {
    if (kDebugMode) {
      print('[API] $message');
    }
  }

  static ApiException _errorFromResponse(http.Response response) {
    String? code;
    String? message;
    try {
      final decoded = json.decode(utf8.decode(response.bodyBytes));
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'];
        if (detail is Map<String, dynamic>) {
          code = detail['code']?.toString();
          message = detail['message']?.toString();
        } else if (detail != null) {
          message = detail.toString();
        }
      }
    } catch (_) {
      // Non-JSON error responses still retain their HTTP status below.
    }
    return ApiException(
      statusCode: response.statusCode,
      code: code,
      message: message ?? 'API request failed',
    );
  }

  static Future<Map<String, dynamic>> get(
    String path, {
    Map<String, String>? params,
    Set<int> expectedErrorStatuses = const {},
  }) async {
    final uri = Uri.parse('$kApiBase$path').replace(queryParameters: params);
    _log('GET $uri');

    try {
      final r = await _httpClient.get(uri);
      _log('GET $uri -> ${r.statusCode}');

      if (r.statusCode != 200) {
        throw _errorFromResponse(r);
      }

      final json = _jsonUtf8(r);
      return json;
    } on ApiException catch (e) {
      if (!expectedErrorStatuses.contains(e.statusCode)) {
        _log('GET $uri -> ERROR: $e');
      }
      rethrow;
    } catch (e) {
      _log('GET $uri -> ERROR: $e');
      rethrow;
    }
  }

  static Future<Map<String, dynamic>> post(String path, {dynamic body}) async {
    final uri = Uri.parse('$kApiBase$path');

    // Convert body to JSON string if it's Map or List
    String? bodyString;
    Map<String, String> headers = {};

    if (body != null) {
      headers['Content-Type'] = 'application/json';
      bodyString = json.encode(body);
    }

    _log('POST $uri body=$bodyString');

    try {
      final r = await _httpClient
          .post(uri, body: bodyString, headers: headers)
          .timeout(const Duration(seconds: 60));
      _log(
        'POST $uri -> status: ${r.statusCode}, size: ${r.bodyBytes.length} bytes',
      );

      if (r.body.isNotEmpty) {
        final preview = r.body.length > 100 ? r.body.substring(0, 100) : r.body;
        _log('Body (first 100): $preview');
      }

      if (r.statusCode != 200) {
        throw _errorFromResponse(r);
      }

      final json = _jsonUtf8(r);
      return json;
    } catch (e) {
      _log('POST $uri -> ERROR: $e');
      rethrow;
    }
  }

  /// バスの現在位置情報を取得する
  /// [routeId] 系統ID (例: odpt.Busroute:Toei.To02)
  /// [tripId] 便ID (必須。バックエンドは一致する便がない場合エラーを返す)
  /// 失敗時は例外を投げる
  static Future<Map<String, dynamic>> fetchBusLocation({
    required String routeId,
    required String tripId,
    String? vehicleId,
    bool forceRefresh = false,
  }) async {
    final params = <String, String>{'route_id': routeId, 'trip_id': tripId};
    if (vehicleId != null) {
      params['vehicle_id'] = vehicleId;
    }
    if (forceRefresh) {
      params['force_refresh'] = 'true';
    }
    if (kDebugMode) {
      params['debug'] = 'true';
    }

    return await get(
      '/bus/location',
      params: params,
      expectedErrorStatuses: const {404},
    );
  }

  /// 都営地下鉄の現在位置情報を取得する。
  ///
  /// route step に GTFS trip_id がある場合はそれを厳密一致で使用する。
  /// まだ trip_id がない経路は、乗車駅・降車駅・到着予定時刻の完全一致で
  /// realtime VehiclePosition と static GTFS の便を一意に解決する。
  static Future<Map<String, dynamic>> fetchTrainLocation({
    String? tripId,
    required String fromName,
    required String toName,
    required String arrivalTime,
    bool forceRefresh = false,
  }) async {
    final params = <String, String>{
      'from_name': fromName,
      'to_name': toName,
      'arrival_time': arrivalTime,
    };
    if (tripId != null && tripId.isNotEmpty) {
      params['trip_id'] = tripId;
    }
    if (forceRefresh) {
      params['force_refresh'] = 'true';
    }

    return await get(
      '/train/location',
      params: params,
      expectedErrorStatuses: const {404},
    );
  }
}
