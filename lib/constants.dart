import 'core/city_profile.dart';

const int kRealtimePollIntervalSeconds = int.fromEnvironment(
  'REALTIME_POLL_INTERVAL_SECONDS',
  defaultValue: 60,
);

Duration get kRealtimePollInterval {
  if (kRealtimePollIntervalSeconds <= 0) {
    throw StateError(
      'REALTIME_POLL_INTERVAL_SECONDS must be greater than zero: '
      '$kRealtimePollIntervalSeconds',
    );
  }
  return Duration(seconds: kRealtimePollIntervalSeconds);
}

const int kRealtimeTransferWarningGraceSeconds = int.fromEnvironment(
  'REALTIME_TRANSFER_WARNING_GRACE_SECONDS',
  defaultValue: 300,
);

Duration get kRealtimeTransferWarningGrace {
  if (kRealtimeTransferWarningGraceSeconds < 0) {
    throw StateError(
      'REALTIME_TRANSFER_WARNING_GRACE_SECONDS must not be negative: '
      '$kRealtimeTransferWarningGraceSeconds',
    );
  }
  return Duration(seconds: kRealtimeTransferWarningGraceSeconds);
}

const String kTokyoApiGoogleDriveFileId = '11eVn1V2mO7x8wPF-Kg9ZExmA-fqTReQ4';
const String kTokyoRuntimeConfigGoogleDriveFileId =
    '1pbE5qFpgDzVhYl8wA1qp4T_7jOsB2s68';
const String kSendaiApiGoogleDriveFileId = '1Frhq_kZt6kEX_smdSdlcKsmTv4vLnjEf';

String? runtimeConfigGoogleDriveFileIdForCity(AppCity city) {
  return switch (city) {
    AppCity.tokyo => kTokyoRuntimeConfigGoogleDriveFileId,
    AppCity.nagoya || AppCity.sendai || AppCity.yokohama => null,
  };
}

String? apiGoogleDriveFileIdForCity(AppCity city) {
  return switch (city) {
    AppCity.tokyo => kTokyoApiGoogleDriveFileId,
    AppCity.sendai => kSendaiApiGoogleDriveFileId,
    AppCity.nagoya || AppCity.yokohama => null,
  };
}

// Explicit developer/build override. In debug/profile builds this takes
// precedence over a city's Google Drive endpoint file. Store builds always
// use Google Drive when a city-specific file is configured.
const String kApiBaseOverride = String.fromEnvironment('API_BASE');

String? _configuredApiBase;

String get kApiBase {
  final String? value = _configuredApiBase;
  if (value == null || value.isEmpty) {
    throw StateError(
      'API base has not been configured. Configure it during app startup '
      'before making API requests.',
    );
  }
  return value;
}

void configureApiBase(Uri uri) {
  if (!uri.hasScheme || uri.host.isEmpty) {
    throw ArgumentError.value(uri, 'uri', 'API base must be an absolute URI.');
  }

  _configuredApiBase = uri.toString().replaceFirst(RegExp(r'/+$'), '');
}
