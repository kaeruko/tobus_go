import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/api_endpoint_source.dart';

void main() {
  test('loads and validates API endpoint from Google Drive', () async {
    final MockClient client = MockClient((http.Request request) async {
      expect(request.url.scheme, 'https');
      expect(request.url.host, 'drive.google.com');
      expect(request.url.path, '/uc');
      expect(request.url.queryParameters['export'], 'download');
      expect(request.url.queryParameters['id'], 'test-file-id');
      expect(request.url.queryParameters['t'], '1234');

      return http.Response(
        'https://example.execute-api.us-west-2.amazonaws.com/\n',
        200,
      );
    });

    final Uri result = await loadApiBaseUriFromGoogleDrive(
      googleDriveFileId: 'test-file-id',
      client: client,
      now: DateTime.fromMillisecondsSinceEpoch(1234),
    );

    expect(
      result,
      Uri.parse('https://example.execute-api.us-west-2.amazonaws.com'),
    );
  });

  test('fails when Google Drive file has multiple non-empty lines', () async {
    final MockClient client = MockClient(
      (_) async => http.Response('https://example.com\nhttps://other.com\n', 200),
    );

    await expectLater(
      loadApiBaseUriFromGoogleDrive(
        googleDriveFileId: 'test-file-id',
        client: client,
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('fails for non-https Drive endpoint', () async {
    final MockClient client = MockClient(
      (_) async => http.Response('http://example.com\n', 200),
    );

    await expectLater(
      loadApiBaseUriFromGoogleDrive(
        googleDriveFileId: 'test-file-id',
        client: client,
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('fails when Google Drive file ID is missing', () async {
    await expectLater(
      loadApiBaseUriFromGoogleDrive(googleDriveFileId: '   '),
      throwsA(isA<StateError>()),
    );
  });

  test('explicit override accepts localhost http for development', () {
    expect(
      parseExplicitApiBaseOverride('http://127.0.0.1:8000/'),
      Uri.parse('http://127.0.0.1:8000'),
    );
  });

  test('explicit override accepts Android emulator host http', () {
    expect(
      parseExplicitApiBaseOverride('http://10.0.2.2:8001/'),
      Uri.parse('http://10.0.2.2:8001'),
    );
  });

  test('explicit override rejects remote http', () {
    expect(
      () => parseExplicitApiBaseOverride('http://example.com'),
      throwsA(isA<StateError>()),
    );
  });
}
