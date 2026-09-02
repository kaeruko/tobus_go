import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/widgets/place_field.dart';

http.Response _jsonResponse(String body, int statusCode) {
  return http.Response.bytes(
    utf8.encode(body),
    statusCode,
    headers: const {'content-type': 'application/json; charset=utf-8'},
  );
}

http.Response _warmupResponse() {
  return _jsonResponse('{"status":"ready","city":"tokyo"}', 200);
}

void main() {
  late http.Client originalClient;

  setUp(() {
    originalClient = ApiClient.httpClient;
    configureApiBase(Uri.parse('https://api.example.test'));
    ApiClient.resetWarmUpForTesting();
  });

  tearDown(() {
    ApiClient.httpClient = originalClient;
    ApiClient.resetWarmUpForTesting();
  });

  testWidgets('typed text is not exposed as a route coordinate', (tester) async {
    var value = '35.0,139.0';
    var description = 'old';
    var autocompleteRequestCount = 0;
    var warmupRequestCount = 0;

    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path.endsWith('/warmup')) {
        warmupRequestCount++;
        return _warmupResponse();
      }
      if (request.url.path.endsWith('/autocomplete')) {
        autocompleteRequestCount++;
        return _jsonResponse('{"predictions":[]}', 200);
      }
      return http.Response('unexpected request', 500);
    });

    await tester.pumpWidget(
      CupertinoApp(
        home: CupertinoPageScaffold(
          child: PlaceField(
            label: '到着(検索)',
            value: value,
            displayValue: description,
            onChanged: (nextValue, nextDescription) {
              value = nextValue;
              description = nextDescription;
            },
          ),
        ),
      ),
    );
    await tester.pump();

    expect(warmupRequestCount, 1);

    await tester.enterText(find.byType(CupertinoTextField), '東京駅');

    expect(value, isEmpty);
    expect(description, '東京駅');
    expect(autocompleteRequestCount, 0);

    await tester.pump(const Duration(milliseconds: 299));
    expect(autocompleteRequestCount, 0);

    await tester.pump(const Duration(milliseconds: 1));
    await tester.pump();
    expect(autocompleteRequestCount, 1);
    expect(warmupRequestCount, 1);
  });

  testWidgets('multiple place fields share one startup warmup request', (
    tester,
  ) async {
    var warmupRequestCount = 0;

    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path.endsWith('/warmup')) {
        warmupRequestCount++;
        return _warmupResponse();
      }
      return http.Response('unexpected request', 500);
    });

    await tester.pumpWidget(
      CupertinoApp(
        home: CupertinoPageScaffold(
          child: Column(
            children: [
              PlaceField(
                label: '出発(検索)',
                value: '',
                displayValue: '',
                onChanged: (_, _) {},
              ),
              PlaceField(
                label: '到着(検索)',
                value: '',
                displayValue: '',
                onChanged: (_, _) {},
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pump();

    expect(warmupRequestCount, 1);
  });

  testWidgets('selecting a suggestion commits only resolved coordinates', (tester) async {
    var value = '';
    var description = '';

    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path.endsWith('/warmup')) {
        return _warmupResponse();
      }
      if (request.url.path.endsWith('/autocomplete')) {
        return _jsonResponse(
          '{"predictions":[{"place_id":"tokyo-station","description":"東京駅, 東京都"}]}',
          200,
        );
      }
      if (request.url.path.endsWith('/details')) {
        return _jsonResponse(
          '{"result":{"name":"東京駅","geometry":{"location":{"lat":35.681236,"lng":139.767125}}}}',
          200,
        );
      }
      return http.Response('unexpected request', 500);
    });

    await tester.pumpWidget(
      CupertinoApp(
        home: CupertinoPageScaffold(
          child: PlaceField(
            label: '到着(検索)',
            value: value,
            displayValue: description,
            onChanged: (nextValue, nextDescription) {
              value = nextValue;
              description = nextDescription;
            },
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(CupertinoTextField), '東京駅');
    expect(value, isEmpty);

    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump();

    expect(find.text('東京駅, 東京都'), findsOneWidget);
    await tester.tap(find.text('東京駅, 東京都'));
    await tester.pumpAndSettle();

    expect(value, '35.681236,139.767125');
    expect(description, '東京駅, 東京都');
  });

  testWidgets('missing detail coordinates are shown as an error, not 0,0', (tester) async {
    var value = '';
    var description = '';

    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path.endsWith('/warmup')) {
        return _warmupResponse();
      }
      if (request.url.path.endsWith('/autocomplete')) {
        return _jsonResponse(
          '{"predictions":[{"place_id":"broken-place","description":"壊れた候補"}]}',
          200,
        );
      }
      if (request.url.path.endsWith('/details')) {
        return _jsonResponse('{"result":{"name":"壊れた候補"}}', 200);
      }
      return http.Response('unexpected request', 500);
    });

    await tester.pumpWidget(
      CupertinoApp(
        home: CupertinoPageScaffold(
          child: PlaceField(
            label: '到着(検索)',
            value: value,
            displayValue: description,
            onChanged: (nextValue, nextDescription) {
              value = nextValue;
              description = nextDescription;
            },
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(CupertinoTextField), '壊れた');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump();
    await tester.tap(find.text('壊れた候補'));
    await tester.pumpAndSettle();

    expect(value, isEmpty);
    expect(find.textContaining('場所の座標を取得できませんでした'), findsOneWidget);
    expect(find.textContaining('0.0,0.0'), findsNothing);
  });

  testWidgets('warmup failure blocks autocomplete instead of bypassing it', (
    tester,
  ) async {
    var autocompleteRequestCount = 0;

    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path.endsWith('/warmup')) {
        return _jsonResponse(
          '{"detail":{"code":"warmup_failed","message":"not ready"}}',
          503,
        );
      }
      if (request.url.path.endsWith('/autocomplete')) {
        autocompleteRequestCount++;
        return _jsonResponse('{"predictions":[]}', 200);
      }
      return http.Response('unexpected request', 500);
    });

    await tester.pumpWidget(
      CupertinoApp(
        home: CupertinoPageScaffold(
          child: PlaceField(
            label: '到着(検索)',
            value: '',
            displayValue: '',
            onChanged: (_, _) {},
          ),
        ),
      ),
    );
    await tester.pump();

    await tester.enterText(find.byType(CupertinoTextField), '東京');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump();

    expect(autocompleteRequestCount, 0);
    expect(find.textContaining('場所候補を取得できませんでした'), findsOneWidget);
    expect(find.textContaining('HTTP 503'), findsOneWidget);
  });
}
