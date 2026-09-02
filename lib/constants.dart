const String kTokyoApiGoogleDriveFileId =
    '11eVn1V2mO7x8wPF-Kg9ZExmA-fqTReQ4';

// Explicit developer/build override. When empty, Tokyo loads its endpoint
// from Google Drive at startup. Other cities must currently provide an
// explicit API_BASE until their own Drive endpoint file is configured.
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
