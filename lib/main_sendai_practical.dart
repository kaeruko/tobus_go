import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'pages/sendai_practical_test_page.dart';
import 'services/sendai_practical_service.dart';

/// Separate opt-in test entry point. No production API URL or saved fare state.
void main() {
  const endpoint = String.fromEnvironment('SENDAI_TEST_API_BASE');
  if (endpoint.isEmpty) throw StateError('SENDAI_TEST_API_BASE is required');
  final service = SendaiPracticalService(baseUri: Uri.parse(endpoint), client: http.Client());
  runApp(MaterialApp(home: SendaiPracticalTestPage(service: service)));
}
