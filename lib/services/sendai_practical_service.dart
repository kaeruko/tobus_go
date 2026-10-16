import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/sendai_practical_models.dart';

/// Explicit test server only, independent of production ApiClient/preferences.
class SendaiPracticalService {
  final Uri baseUri;
  final http.Client client;
  SendaiPracticalService({required this.baseUri, required this.client}) {
    if ((!['http', 'https'].contains(baseUri.scheme)) ||
        baseUri.host.isEmpty || baseUri.userInfo.isNotEmpty ||
        baseUri.hasQuery || baseUri.hasFragment) {
      throw ArgumentError('An explicit test server origin is required');
    }
  }

  Map<String, dynamic> _decode(http.Response response) {
    if (response.statusCode != 200) {
      throw StateError('検証検索が停止しました（HTTP ${response.statusCode}）: '
          '${utf8.decode(response.bodyBytes)}');
    }
    return jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
  }

  Future<SendaiPracticalCapabilities> capabilities() async =>
      SendaiPracticalCapabilities.fromJson(_decode(await client
          .get(baseUri.resolve('/test/sendai/capabilities'))
          .timeout(const Duration(seconds: 20))));

  Future<List<SendaiPracticalCandidate>> search({
    required String originStopId, required String destinationStopId,
    required String civilDate, required int departureMinute,
    required String farePolicyId, required bool acceptExperimentalTransfers,
  }) async {
    if (farePolicyId != 'sendai_fureai_pass' || !acceptExperimentalTransfers) {
      throw ArgumentError('パスと仮の乗換モデルの明示選択が必要です');
    }
    final body = _decode(await client.post(baseUri.resolve('/test/sendai/route'),
        headers: {'Content-Type': 'application/json'}, body: jsonEncode({
          'origin_stop_id': originStopId, 'destination_stop_id': destinationStopId,
          'civil_date': civilDate, 'departure_minute': departureMinute,
          'fare_policy_id': farePolicyId,
          'accept_experimental_transfer_model': acceptExperimentalTransfers,
        })).timeout(const Duration(seconds: 25)));
    if (body['schema'] != 'sendai_practical_route_v1') {
      throw const FormatException('Unexpected route schema');
    }
    return (body['candidates'] as List).map((e) =>
        SendaiPracticalCandidate.fromJson(e as Map<String, dynamic>)).toList();
  }
}
