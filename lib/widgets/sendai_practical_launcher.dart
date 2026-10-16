import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../pages/sendai_practical_test_page.dart';
import '../services/sendai_practical_service.dart';

/// Development entry in the ordinary Sendai screen. No production API switch.
bool showSendaiPracticalEntry({required String city, required bool debugBuild,
    required String endpoint}) {
  if (city != 'sendai' || !debugBuild || endpoint.isEmpty) return false;
  final uri = Uri.parse(endpoint);
  if (!['http', 'https'].contains(uri.scheme) || uri.host.isEmpty ||
      uri.userInfo.isNotEmpty || uri.hasQuery || uri.hasFragment ||
      (uri.path.isNotEmpty && uri.path != '/')) {
    throw ArgumentError('An explicit test server origin is required');
  }
  return true;
}

class SendaiPracticalLauncher extends StatelessWidget {
  final String city;
  final bool debugBuild;
  final String endpoint;
  const SendaiPracticalLauncher({super.key, required this.city,
    this.debugBuild = kDebugMode,
    this.endpoint = const String.fromEnvironment('SENDAI_TEST_API_BASE')});

  @override
  Widget build(BuildContext context) {
    if (!showSendaiPracticalEntry(city: city, debugBuild: debugBuild, endpoint: endpoint)) {
      return const SizedBox.shrink();
    }
    return CupertinoButton(
      key: const Key('sendai-practical-entry'),
      child: const Text('ふれあい乗車証の対応区間を試す（開発版）'),
      onPressed: () async {
        final client = http.Client();
        try {
          await Navigator.of(context).push(CupertinoPageRoute<void>(builder: (_) =>
            SendaiPracticalTestPage(service: SendaiPracticalService(
              baseUri: Uri.parse(endpoint), client: client))));
        } finally {
          client.close();
        }
      });
  }
}
