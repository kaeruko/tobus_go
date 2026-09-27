import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_endpoint_source.dart';

const Duration runtimeConfigFetchTimeout = Duration(seconds: 12);

class RuntimeConfig {
  final int schemaVersion;
  final Uri apiBase;
  final AppVersion latestVersion;
  final AppVersion minimumSupportedVersion;
  final String updateMessageJa;
  final String updateMessageEn;
  final Uri? androidStoreUrl;
  final Uri? iosStoreUrl;

  const RuntimeConfig({
    required this.schemaVersion,
    required this.apiBase,
    required this.latestVersion,
    required this.minimumSupportedVersion,
    required this.updateMessageJa,
    required this.updateMessageEn,
    this.androidStoreUrl,
    this.iosStoreUrl,
  });

  factory RuntimeConfig.fromJson(Map<String, dynamic> json) {
    const allowedKeys = <String>{
      'schema_version',
      'api_base',
      'latest_version',
      'minimum_supported_version',
      'update_message_ja',
      'update_message_en',
      'android_store_url',
      'ios_store_url',
    };
    final unknownKeys = json.keys.where((key) => !allowedKeys.contains(key));
    if (unknownKeys.isNotEmpty) {
      throw FormatException(
        'Runtime config contains unsupported keys: '
        '${unknownKeys.join(', ')}',
      );
    }

    final schemaVersion = json['schema_version'];
    if (schemaVersion is! int || schemaVersion != 1) {
      throw StateError(
        'Unsupported runtime config schema_version: $schemaVersion',
      );
    }

    final apiBaseRaw = _requiredString(json, 'api_base');
    final latestVersion = AppVersion.parse(
      _requiredString(json, 'latest_version'),
      fieldName: 'latest_version',
    );
    final minimumSupportedVersion = AppVersion.parse(
      _requiredString(json, 'minimum_supported_version'),
      fieldName: 'minimum_supported_version',
    );
    if (latestVersion < minimumSupportedVersion) {
      throw StateError(
        'Runtime config latest_version must be >= '
        'minimum_supported_version: latest=$latestVersion '
        'minimum=$minimumSupportedVersion',
      );
    }

    return RuntimeConfig(
      schemaVersion: schemaVersion as int,
      apiBase: validatePublicApiBaseUri(
        apiBaseRaw,
        sourceName: 'Runtime config api_base',
      ),
      latestVersion: latestVersion,
      minimumSupportedVersion: minimumSupportedVersion,
      updateMessageJa: _requiredString(json, 'update_message_ja'),
      updateMessageEn: _requiredString(json, 'update_message_en'),
      androidStoreUrl: _optionalHttpsUri(json, 'android_store_url'),
      iosStoreUrl: _optionalHttpsUri(json, 'ios_store_url'),
    );
  }

  String updateMessageForLanguage(String languageCode) {
    return languageCode == 'ja' ? updateMessageJa : updateMessageEn;
  }

  bool requiresUpdate(AppVersion currentVersion) {
    return currentVersion < minimumSupportedVersion;
  }
}

class AppVersion implements Comparable<AppVersion> {
  final int major;
  final int minor;
  final int patch;

  const AppVersion(this.major, this.minor, this.patch);

  factory AppVersion.parse(
    String raw, {
    String fieldName = 'version',
  }) {
    final match = RegExp(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
        .firstMatch(raw.trim());
    if (match == null) {
      throw FormatException(
        '$fieldName must use strict major.minor.patch format.',
        raw,
      );
    }
    return AppVersion(
      int.parse(match.group(1)!),
      int.parse(match.group(2)!),
      int.parse(match.group(3)!),
    );
  }

  @override
  int compareTo(AppVersion other) {
    final majorCompare = major.compareTo(other.major);
    if (majorCompare != 0) return majorCompare;
    final minorCompare = minor.compareTo(other.minor);
    if (minorCompare != 0) return minorCompare;
    return patch.compareTo(other.patch);
  }

  bool operator <(AppVersion other) => compareTo(other) < 0;

  bool operator <=(AppVersion other) => compareTo(other) <= 0;

  bool operator >(AppVersion other) => compareTo(other) > 0;

  bool operator >=(AppVersion other) => compareTo(other) >= 0;

  @override
  bool operator ==(Object other) {
    return other is AppVersion &&
        major == other.major &&
        minor == other.minor &&
        patch == other.patch;
  }

  @override
  int get hashCode => Object.hash(major, minor, patch);

  @override
  String toString() => '$major.$minor.$patch';
}

Future<RuntimeConfig> loadRuntimeConfigFromGoogleDrive({
  required String googleDriveFileId,
  http.Client? client,
  DateTime? now,
}) async {
  final fileId = googleDriveFileId.trim();
  if (fileId.isEmpty) {
    throw StateError('Google Drive runtime config file ID is not configured.');
  }

  final ownsClient = client == null;
  final httpClient = client ?? http.Client();

  try {
    final downloadUri = Uri.https(
      'drive.google.com',
      '/uc',
      <String, String>{
        'export': 'download',
        'id': fileId,
        't': (now ?? DateTime.now()).millisecondsSinceEpoch.toString(),
      },
    );

    final response = await httpClient
        .get(downloadUri)
        .timeout(runtimeConfigFetchTimeout);
    if (response.statusCode != 200) {
      throw StateError(
        'Google Drive runtime config fetch failed: '
        'HTTP ${response.statusCode} from $downloadUri',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw FormatException('Runtime config root must be a JSON object.');
    }
    return RuntimeConfig.fromJson(decoded);
  } finally {
    if (ownsClient) {
      httpClient.close();
    }
  }
}

String _requiredString(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value is! String || value.trim().isEmpty) {
    throw FormatException('Runtime config field $key must be a non-empty string.');
  }
  return value.trim();
}

Uri? _optionalHttpsUri(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value == null) return null;
  if (value is! String || value.trim().isEmpty) {
    throw FormatException(
      'Runtime config field $key must be a non-empty https URL when present.',
    );
  }
  final uri = Uri.tryParse(value.trim());
  if (uri == null ||
      uri.scheme != 'https' ||
      uri.host.isEmpty ||
      uri.fragment.isNotEmpty) {
    throw FormatException(
      'Runtime config field $key must be an absolute https URL.',
      value,
    );
  }
  return uri;
}
