import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/runtime_config_source.dart';

void main() {
  test('loads and validates runtime config from Google Drive', () async {
    final client = MockClient((http.Request request) async {
      expect(request.url.scheme, 'https');
      expect(request.url.host, 'drive.google.com');
      expect(request.url.path, '/uc');
      expect(request.url.queryParameters['export'], 'download');
      expect(request.url.queryParameters['id'], 'runtime-config-id');
      expect(request.url.queryParameters['t'], '1234');

      return http.Response(
        '''
{
  "schema_version": 1,
  "api_base": "https://example.lambda-url.us-west-2.on.aws/",
  "latest_version": "1.0.3",
  "minimum_supported_version": "1.0.1",
  "update_message_ja": "最新版へ更新してください。",
  "update_message_en": "Please update."
}
''',
        200,
      );
    });

    final config = await loadRuntimeConfigFromGoogleDrive(
      googleDriveFileId: 'runtime-config-id',
      client: client,
      now: DateTime.fromMillisecondsSinceEpoch(1234),
    );

    expect(
      config.apiBase,
      Uri.parse('https://example.lambda-url.us-west-2.on.aws'),
    );
    expect(config.latestVersion, const AppVersion(1, 0, 3));
    expect(config.minimumSupportedVersion, const AppVersion(1, 0, 1));
    expect(config.requiresUpdate(const AppVersion(1, 0, 0)), isTrue);
    expect(config.requiresUpdate(const AppVersion(1, 0, 1)), isFalse);
    expect(config.requiresUpdate(const AppVersion(1, 0, 3)), isFalse);
  });

  test('version comparison is numeric rather than lexical', () {
    expect(
      AppVersion.parse('1.10.0') > AppVersion.parse('1.9.9'),
      isTrue,
    );
    expect(
      AppVersion.parse('2.0.0') > AppVersion.parse('1.99.99'),
      isTrue,
    );
  });

  test('rejects malformed semantic versions', () {
    expect(
      () => AppVersion.parse('1.0'),
      throwsA(isA<FormatException>()),
    );
    expect(
      () => AppVersion.parse('01.0.0'),
      throwsA(isA<FormatException>()),
    );
    expect(
      () => AppVersion.parse('1.0.0+19'),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects unsupported runtime config keys', () {
    expect(
      () => RuntimeConfig.fromJson({
        'schema_version': 1,
        'api_base': 'https://example.com',
        'latest_version': '1.0.3',
        'minimum_supported_version': '1.0.1',
        'update_message_ja': '更新',
        'update_message_en': 'Update',
        'typo_version': '1.2.3',
      }),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects latest version below minimum supported version', () {
    expect(
      () => RuntimeConfig.fromJson({
        'schema_version': 1,
        'api_base': 'https://example.com',
        'latest_version': '1.0.0',
        'minimum_supported_version': '1.0.1',
        'update_message_ja': '更新',
        'update_message_en': 'Update',
      }),
      throwsA(isA<StateError>()),
    );
  });

  test('accepts optional store URLs only as https', () {
    final config = RuntimeConfig.fromJson({
      'schema_version': 1,
      'api_base': 'https://example.com',
      'latest_version': '1.0.3',
      'minimum_supported_version': '1.0.1',
      'update_message_ja': '更新',
      'update_message_en': 'Update',
      'android_store_url': 'https://play.google.com/store/apps/details?id=x',
      'ios_store_url': 'https://apps.apple.com/app/id123',
    });

    expect(config.androidStoreUrl?.scheme, 'https');
    expect(config.iosStoreUrl?.scheme, 'https');
  });
}
