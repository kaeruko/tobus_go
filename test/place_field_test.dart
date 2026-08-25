import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/widgets/place_field.dart';

void main() {
  late http.Client originalClient;

  setUp(() {
    originalClient = ApiClient.httpClient;
  });

  tearDown(() {
    ApiClient.httpClient = originalClient;
  });

  testWidgets('typed text is not exposed as a route coordinate', (tester) async {
    var value = '35.0,139.0';
    var description = 'old';
    var requestCount = 0;

    ApiClient.httpClient = MockClient((request) async {
      requestCount++;
      return http.Response('{"predictions":[]}', 200);
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
    expect(description, '東京駅');
    expect(requestCount, 0);

    await tester.pump(const Duration(milliseconds: 299));
    expect(requestCount, 0);

    await tester.pump(const Duration(milliseconds: 1));
    await tester.pump();
    expect(requestCount, 1);
  });

  testWidgets('selecting a suggestion commits only resolved coordinates', (tester) async {
    var value = '';
    var description = '';

    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path.endsWith('/autocomplete')) {
        return http.Response(
          '{"predictions":[{"place_id":"tokyo-station","description":"東京駅, 東京都"}]}',
          200,
        );
      }
      if (request.url.path.endsWith('/details')) {
        return http.Response(
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
      if (request.url.path.endsWith('/autocomplete')) {
        return http.Response(
          '{"predictions":[{"place_id":"broken-place","description":"壊れた候補"}]}',
          200,
        );
      }
      if (request.url.path.endsWith('/details')) {
        return http.Response('{"result":{"name":"壊れた候補"}}', 200);
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
}
