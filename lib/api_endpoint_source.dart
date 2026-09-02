import 'package:http/http.dart' as http;

const Duration apiEndpointFetchTimeout = Duration(seconds: 12);

Future<Uri> loadApiBaseUriFromGoogleDrive({
  required String googleDriveFileId,
  http.Client? client,
  DateTime? now,
}) async {
  final String fileId = googleDriveFileId.trim();
  if (fileId.isEmpty) {
    throw StateError('Google Drive API file ID is not configured.');
  }

  final bool ownsClient = client == null;
  final http.Client httpClient = client ?? http.Client();

  try {
    final Uri downloadUri = Uri.https(
      'drive.google.com',
      '/uc',
      <String, String>{
        'export': 'download',
        'id': fileId,
        't': (now ?? DateTime.now()).millisecondsSinceEpoch.toString(),
      },
    );

    final http.Response response = await httpClient
        .get(downloadUri)
        .timeout(apiEndpointFetchTimeout);

    if (response.statusCode != 200) {
      throw StateError(
        'Google Drive API endpoint fetch failed: '
        'HTTP ${response.statusCode} from $downloadUri',
      );
    }

    final List<String> nonEmptyLines = response.body
        .split(RegExp(r'\r?\n'))
        .map((String line) => line.trim())
        .where((String line) => line.isNotEmpty)
        .toList(growable: false);

    if (nonEmptyLines.length != 1) {
      throw StateError(
        'Google Drive API endpoint file must contain exactly one non-empty line; '
        'found ${nonEmptyLines.length}.',
      );
    }

    return validatePublicApiBaseUri(
      nonEmptyLines.single,
      sourceName: 'Google Drive API endpoint',
    );
  } finally {
    if (ownsClient) {
      httpClient.close();
    }
  }
}

Uri validatePublicApiBaseUri(
  String raw, {
  required String sourceName,
}) {
  final Uri? parsed = Uri.tryParse(raw.trim());
  if (parsed == null || !parsed.hasScheme || parsed.host.isEmpty) {
    throw FormatException('$sourceName is not a valid absolute URI.', raw);
  }

  if (parsed.scheme != 'https') {
    throw StateError('$sourceName must use https. URI=$parsed');
  }

  if (parsed.host == '127.0.0.1' || parsed.host == 'localhost') {
    throw StateError('$sourceName must not use a local host. URI=$parsed');
  }

  if (parsed.query.isNotEmpty || parsed.fragment.isNotEmpty) {
    throw StateError(
      '$sourceName must be a base URL without query or fragment. URI=$parsed',
    );
  }

  return Uri.parse(parsed.toString().replaceFirst(RegExp(r'/+$'), ''));
}

Uri parseExplicitApiBaseOverride(String raw) {
  final Uri? parsed = Uri.tryParse(raw.trim());
  if (parsed == null || !parsed.hasScheme || parsed.host.isEmpty) {
    throw FormatException('API_BASE is not a valid absolute URI.', raw);
  }

  final bool isLocalHost =
      parsed.host == '127.0.0.1' || parsed.host == 'localhost';
  final bool validScheme = parsed.scheme == 'https' ||
      (isLocalHost && parsed.scheme == 'http');
  if (!validScheme) {
    throw StateError(
      'API_BASE must use https, except http is allowed for localhost. '
      'URI=$parsed',
    );
  }

  if (parsed.query.isNotEmpty || parsed.fragment.isNotEmpty) {
    throw StateError(
      'API_BASE must be a base URL without query or fragment. URI=$parsed',
    );
  }

  return Uri.parse(parsed.toString().replaceFirst(RegExp(r'/+$'), ''));
}
