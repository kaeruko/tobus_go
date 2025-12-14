import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../constants.dart';

class ApiClient {
  static Map<String, dynamic> _jsonUtf8(http.Response r) {
    final body = utf8.decode(r.bodyBytes);
    _log('Response body (${body.length} chars): ${_truncate(body)}');
    return json.decode(body) as Map<String, dynamic>;
  }

  static void _log(String message) {
    if (kDebugMode) {
      print('[API] $message');
    }
  }

  static String _truncate(String body, {int max = 1000}) {
    if (body.length <= max) {
      return body;
    }

    return '${body.substring(0, max)}...(+${body.length - max} chars)';
  }

  static Future<Map<String, dynamic>> get(String path, {Map<String, String>? params}) async {
    final uri = Uri.parse('$kApiBase$path').replace(queryParameters: params);
    _log('GET $uri');
    
    try {
      final r = await http.get(uri);
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

  static Future<Map<String, dynamic>> post(String path, {Map<String, String>? body}) async {
    final uri = Uri.parse('$kApiBase$path');
    _log('POST $uri body=$body');
    
    try {
      final r = await http.post(uri, body: body);
      _log('POST $uri -> ${r.statusCode}');
      
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
}
