import 'package:http/http.dart' as http;

const Duration apiEndpointFetchTimeout = Duration(seconds: 12);

Future<Uri> loadApiBaseUriFromGoogleDrive({
  required String googleDriveFileId,
  http.Client? client,
  DateTime? now,
}) async {
  final String fileId = googleDriveFileId.trim();
  if (fileId.isEmpty || fileId == 'REPLACE_WITH_TOBUS_GO_API_FILE_ID') {
    throw StateError(
      'Google Drive API file ID is not configured. '
      'Set kApiGoogleDriveFileId in constants.dart.',
    );
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

    final Uri? parsed = Uri.tryParse(nonEmptyLines.single);
    if (parsed == null || !parsed.hasScheme || parsed.host.isEmpty) {
      throw FormatException(
        'Google Drive API endpoint is not a valid absolute URI.',
        nonEmptyLines.single,
      );
    }

    if (parsed.scheme != 'https') {
      throw StateError(
        'Google Drive API endpoint must use https. URI=$parsed',
      );
    }

    if (parsed.host == '127.0.0.1' || parsed.host == 'localhost') {
      throw StateError(
        'Google Drive API endpoint must not use a local host. URI=$parsed',
      );
    }

    if (parsed.query.isNotEmpty || parsed.fragment.isNotEmpty) {
      throw StateError(
        'Google Drive API endpoint must be a base URL without query or fragment. '
        'URI=$parsed',
      );
    }

    return Uri.parse(parsed.toString().replaceFirst(RegExp(r'/+$'), ''));
  } finally {
    if (ownsClient) {
      httpClient.close();
    }
  }
}
