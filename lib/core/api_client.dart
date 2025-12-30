import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../constants.dart';

class ApiClient {
  static http.Client httpClient = http.Client();

  static Map<String, dynamic> _jsonUtf8(http.Response r) {
    final body = utf8.decode(r.bodyBytes);
    return json.decode(body) as Map<String, dynamic>;
  }

  static void _log(String message) {
    if (kDebugMode) {
      print('[API] $message');
    }
  }

  static Future<Map<String, dynamic>> get(String path, {Map<String, String>? params}) async {
    final uri = Uri.parse('$kApiBase$path').replace(queryParameters: params);
    _log('GET $uri');

    try {
      final r = await httpClient.get(uri);
      _log('GET $uri -> ${r.statusCode}');
      
      if (r.statusCode != 200) {
        throw Exception('HTTP ${r.statusCode}');
      }
      
      final json = _jsonUtf8(r);
      return json;
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
      final r =
          await httpClient.post(uri, body: bodyString, headers: headers).timeout(const Duration(seconds: 60));
      _log('POST $uri -> status: ${r.statusCode}, size: ${r.bodyBytes.length} bytes');
      
      if (r.body.isNotEmpty) {
        final preview = r.body.length > 100 ? r.body.substring(0, 100) : r.body;
        _log('Body (first 100): $preview');
      }

      if (r.statusCode != 200) {
        throw Exception('HTTP ${r.statusCode}');
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
  /// [tripId] 便ID (指定すると特定の車両を追跡できます)
  /// 失敗時は例外を投げる
  static Future<Map<String, dynamic>> fetchBusLocation({
    required String routeId,
    String? tripId,
  }) async {
    final params = <String, String>{
      'route_id': routeId,
    };
    
    if (tripId != null) {
      params['trip_id'] = tripId;
    }

    return await get('/bus/location', params: params);
  }
}
