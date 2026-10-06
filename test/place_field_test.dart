import 'dart:async';
import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/l10n/app_localizations.dart';
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

  testWidgets('changing language preserves a pending place selection', (
    tester,
  ) async {
    final locale = ValueNotifier(const Locale('ja'));
    addTearDown(locale.dispose);
    final details = <String, Completer<http.Response>>{};
    var selectedValue = '';
    var selectedName = '';
    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path == '/warmup') return _warmupResponse();
      if (request.url.path == '/autocomplete') {
        return _jsonResponse(
          jsonEncode({
            'predictions': [
              {'place_id': 'tokyo', 'description': '東京駅'},
            ],
          }),
          200,
        );
      }
      final language = request.url.queryParameters['lang']!;
      return (details[language] = Completer<http.Response>()).future;
    });
    await tester.pumpWidget(
      ValueListenableBuilder<Locale>(
        valueListenable: locale,
        builder: (context, value, child) => CupertinoApp(
          locale: value,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CupertinoPageScaffold(
            child: PlaceField(
              label: 'Destination',
              value: '',
              displayValue: '',
              onChanged: (value, name) {
                selectedValue = value;
                selectedName = name;
              },
            ),
          ),
        ),
      ),
    );
    await tester.enterText(find.byType(CupertinoTextField), 'Tokyo');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    await tester.tap(find.text('東京駅'));
    await tester.pump();
    expect(details.keys, unorderedEquals(['ja', 'en']));
    locale.value = const Locale('zh');
    await tester.pump();
    await tester.pump();
    for (final entry in details.entries) {
      entry.value.complete(
        _jsonResponse(
          jsonEncode({
            'result': {
              'name': entry.key == 'ja' ? '東京駅' : 'Tokyo Station',
              'geometry': {
                'location': {'lat': 35.0, 'lng': 139.0},
              },
            },
          }),
          200,
        ),
      );
    }
    await tester.pumpAndSettle();
    expect(selectedValue, '35.0,139.0');
    expect(selectedName, 'Tokyo Station');
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'Chinese IME waits for confirmation and reuses two details calls',
    (tester) async {
      final autocompleteLanguages = <String?>[];
      final detailLanguages = <String?>[];
      String? selected;
      ApiClient.httpClient = MockClient((request) async {
        if (request.url.path == '/warmup') return _warmupResponse();
        if (request.url.path == '/autocomplete') {
          autocompleteLanguages.add(request.url.queryParameters['lang']);
          return _jsonResponse(
            jsonEncode({
              'predictions': [
                {'place_id': 'tokyo', 'description': 'Tokyo Station'},
              ],
            }),
            200,
          );
        }
        if (request.url.path == '/details') {
          final language = request.url.queryParameters['lang'];
          detailLanguages.add(language);
          return _jsonResponse(
            jsonEncode({
              'result': {
                'name': language == 'ja' ? '東京駅' : 'Tokyo Station',
                'geometry': {
                  'location': {'lat': 35.0, 'lng': 139.0},
                },
              },
            }),
            200,
          );
        }
        return http.Response('Unexpected request', 500);
      });
      await tester.pumpWidget(
        CupertinoApp(
          locale: const Locale('zh'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CupertinoPageScaffold(
            child: PlaceField(
              label: '目的地',
              value: '',
              displayValue: '',
              onChanged: (value, _) => selected = value,
            ),
          ),
        ),
      );
      await tester.showKeyboard(find.byType(CupertinoTextField));
      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: 'dongjing',
          selection: TextSelection.collapsed(offset: 8),
          composing: TextRange(start: 0, end: 8),
        ),
      );
      await tester.pump(const Duration(seconds: 1));
      expect(autocompleteLanguages, isEmpty);
      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: '东京',
          selection: TextSelection.collapsed(offset: 2),
        ),
      );
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pumpAndSettle();
      expect(autocompleteLanguages, ['en']);
      await tester.tap(find.text('Tokyo Station'));
      await tester.pumpAndSettle();
      expect(detailLanguages, unorderedEquals(['ja', 'en']));
      expect(selected, '35.0,139.0');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('typed text is not exposed as a route coordinate', (
    tester,
  ) async {
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
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
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
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
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

  testWidgets('selecting a suggestion commits only resolved coordinates', (
    tester,
  ) async {
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
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
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
    expect(description, '東京駅');
  });

  testWidgets(
    'generic chome detail expands to town and chome from formatted address',
    (tester) async {
      var resolvedValue = '';
      var resolvedDisplay = '';
      var resolvedJa = '';
      var resolvedEn = '';

      ApiClient.httpClient = MockClient((request) async {
        if (request.url.path.endsWith('/warmup')) {
          return _warmupResponse();
        }
        if (request.url.path.endsWith('/autocomplete')) {
          return _jsonResponse(
            '{"predictions":[{"place_id":"hirai-7","description":"日本、東京都江戸川区平井7丁目8-8"}]}',
            200,
          );
        }
        if (request.url.path.endsWith('/details')) {
          final lang = request.url.queryParameters['lang'];
          if (lang == 'ja') {
            return _jsonResponse(
              '{"result":{"name":"7丁目","formatted_address":"日本、東京都江戸川区平井7丁目8-8","geometry":{"location":{"lat":35.706,"lng":139.842}}}}',
              200,
            );
          }
          if (lang == 'en') {
            return _jsonResponse(
              '{"result":{"name":"Hirai 7-chome","formatted_address":"7 Chome-8-8 Hirai, Edogawa City, Tokyo, Japan","geometry":{"location":{"lat":35.706,"lng":139.842}}}}',
              200,
            );
          }
          return http.Response('unexpected details language', 500);
        }
        return http.Response('unexpected request', 500);
      });

      await tester.pumpWidget(
        CupertinoApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CupertinoPageScaffold(
            child: PlaceField(
              label: '出発(検索)',
              value: '',
              displayValue: '',
              onChanged: (_, _) {},
              onResolved: (value, display, nameJa, nameEn) {
                resolvedValue = value;
                resolvedDisplay = display;
                resolvedJa = nameJa;
                resolvedEn = nameEn;
              },
            ),
          ),
        ),
      );

      await tester.enterText(find.byType(CupertinoTextField), '平井七丁目');
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pump();

      expect(find.text('日本、東京都江戸川区平井7丁目8-8'), findsOneWidget);
      await tester.tap(find.text('日本、東京都江戸川区平井7丁目8-8'));
      await tester.pumpAndSettle();

      expect(resolvedValue, '35.706,139.842');
      expect(resolvedDisplay, '平井7丁目');
      expect(resolvedJa, '平井7丁目');
      expect(resolvedEn, 'Hirai 7-chome');
      expect(
        tester
            .widget<CupertinoTextField>(find.byType(CupertinoTextField))
            .controller!
            .text,
        '平井7丁目',
      );
    },
  );

  testWidgets('missing detail coordinates are shown as an error, not 0,0', (
    tester,
  ) async {
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
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
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
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
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
  testWidgets('Korean locale uses English place search and keeps Japanese names', (
    tester,
  ) async {
    var autocompleteLang = '';
    final detailsLangs = <String>{};
    var resolvedJa = '';
    var resolvedEn = '';
    var resolvedDisplay = '';

    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path.endsWith('/warmup')) {
        return _warmupResponse();
      }
      if (request.url.path.endsWith('/autocomplete')) {
        autocompleteLang = request.url.queryParameters['lang'] ?? '';
        return _jsonResponse(
          '{"predictions":[{"place_id":"tokyo-station","description":"Tokyo Station, Tokyo"}]}',
          200,
        );
      }
      if (request.url.path.endsWith('/details')) {
        final lang = request.url.queryParameters['lang'] ?? '';
        detailsLangs.add(lang);
        final name = lang == 'ja' ? '東京駅' : 'Tokyo Station';
        return _jsonResponse(
          '{"result":{"name":"$name","geometry":{"location":{"lat":35.681236,"lng":139.767125}}}}',
          200,
        );
      }
      return http.Response('unexpected request', 500);
    });

    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: CupertinoPageScaffold(
          child: PlaceField(
            label: '도착지',
            value: '',
            displayValue: '',
            onChanged: (_, _) {},
            onResolved: (value, display, nameJa, nameEn) {
              resolvedDisplay = display;
              resolvedJa = nameJa;
              resolvedEn = nameEn;
            },
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(CupertinoTextField), 'Tokyo');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump();

    expect(autocompleteLang, 'en');
    expect(find.text('Tokyo Station, Tokyo'), findsOneWidget);

    await tester.tap(find.text('Tokyo Station, Tokyo'));
    await tester.pumpAndSettle();

    expect(detailsLangs, {'ja', 'en'});
    expect(resolvedDisplay, 'Tokyo Station');
    expect(resolvedJa, '東京駅');
    expect(resolvedEn, 'Tokyo Station');
    expect(tester.takeException(), isNull);
  });

  testWidgets('English locale resolves both Japanese and English place names', (
    tester,
  ) async {
    var autocompleteLang = '';
    final detailsLangs = <String>{};
    var resolvedJa = '';
    var resolvedEn = '';
    var resolvedDisplay = '';

    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path.endsWith('/warmup')) {
        return _warmupResponse();
      }
      if (request.url.path.endsWith('/autocomplete')) {
        autocompleteLang = request.url.queryParameters['lang'] ?? '';
        return _jsonResponse(
          '{"predictions":[{"place_id":"tokyo-station","description":"Tokyo Station, Tokyo"}]}',
          200,
        );
      }
      if (request.url.path.endsWith('/details')) {
        final lang = request.url.queryParameters['lang'] ?? '';
        detailsLangs.add(lang);
        final name = lang == 'ja' ? '東京駅' : 'Tokyo Station';
        return _jsonResponse(
          '{"result":{"name":"$name","geometry":{"location":{"lat":35.681236,"lng":139.767125}}}}',
          200,
        );
      }
      return http.Response('unexpected request', 500);
    });

    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: CupertinoPageScaffold(
          child: PlaceField(
            label: 'To',
            value: '',
            displayValue: '',
            onChanged: (_, _) {},
            onResolved: (value, display, nameJa, nameEn) {
              resolvedDisplay = display;
              resolvedJa = nameJa;
              resolvedEn = nameEn;
            },
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(CupertinoTextField), 'Tokyo');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump();

    expect(autocompleteLang, 'en');
    expect(find.text('Tokyo Station, Tokyo'), findsOneWidget);

    await tester.tap(find.text('Tokyo Station, Tokyo'));
    await tester.pumpAndSettle();

    expect(detailsLangs, {'ja', 'en'});
    expect(resolvedDisplay, 'Tokyo Station');
    expect(resolvedJa, '東京駅');
    expect(resolvedEn, 'Tokyo Station');
  });
}
