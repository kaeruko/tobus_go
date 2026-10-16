import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show Material, MaterialType;
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
  /// Test injection only. Production defaults to a fresh HTTP client.
  final http.Client Function()? clientFactory;
  const SendaiPracticalLauncher({super.key, required this.city,
    this.debugBuild = kDebugMode,
    this.endpoint = const String.fromEnvironment('SENDAI_TEST_API_BASE'),
    this.clientFactory});

  @override
  Widget build(BuildContext context) {
    if (!showSendaiPracticalEntry(city: city, debugBuild: debugBuild, endpoint: endpoint)) {
      return const SizedBox.shrink();
    }
    return Column(mainAxisSize: MainAxisSize.min, children: [
      CupertinoButton(
        key: const Key('sendai-practical-entry'),
        child: const Text('ふれあい乗車証の対応区間を試す（開発版）'),
        onPressed: () async {
          final client = clientFactory?.call() ?? http.Client();
          try {
            await Navigator.of(context).push(CupertinoPageRoute<void>(builder: (_) =>
              SendaiPracticalTestPage(service: SendaiPracticalService(
                baseUri: Uri.parse(endpoint), client: client))));
          } finally {
            client.close();
          }
        },
      ),
      _InlineSendaiPracticalForm(endpoint: endpoint, clientFactory: clientFactory),
    ]);
  }
}

/// Explicitly expanded form on the ordinary Sendai search tab. No production route call.
class _InlineSendaiPracticalForm extends StatefulWidget {
  final String endpoint;
  final http.Client Function()? clientFactory;
  const _InlineSendaiPracticalForm({required this.endpoint, this.clientFactory});

  @override
  State<_InlineSendaiPracticalForm> createState() => _InlineSendaiPracticalFormState();
}

class _InlineSendaiPracticalFormState extends State<_InlineSendaiPracticalForm> {
  bool _open = false;
  http.Client? _client;

  @override
  void dispose() {
    _client?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(children: [
    CupertinoButton(
      key: const Key('sendai-practical-inline-toggle'),
      child: Text(_open ? '開発用の経路条件を閉じる' : 'この画面で出発地・目的地・日時・乗車証を設定'),
      onPressed: () => setState(() {
        _open = !_open;
        if (_open) _client ??= widget.clientFactory?.call() ?? http.Client();
      }),
    ),
    if (_open)
      SizedBox(
        height: 640,
        child: Material(
          type: MaterialType.transparency,
          child: SendaiPracticalTestPage(
            embedded: true,
            service: SendaiPracticalService(
              baseUri: Uri.parse(widget.endpoint), client: _client!),
          ),
        ),
      ),
  ]);
}
