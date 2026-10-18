import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/providers/route_search_provider.dart';
import 'package:toeigo/services/route_search_service.dart';
import 'package:toeigo/widgets/route_search_error_notice.dart';

class _OriginalFailureService implements RouteSearchService {
  final Object error;
  final StackTrace stack;
  int calls = 0;

  _OriginalFailureService(this.error, this.stack);

  @override
  Future<RouteSearchResult> search(RouteSearchRequest request) {
    calls++;
    return Future.error(error, stack);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late http.Client originalClient;
  late List<Map<String, dynamic>> requests;
  late String errorCode;
  const diagnostic = {'reason': 'max_visited', 'visited': 100001, 'queue': 16690};
  const rawMessage = 'fewTransfers search safety limit exceeded: '
      'visited=100001 queue=16690';

  setUp(() {
    originalClient = ApiClient.httpClient;
    requests = [];
    errorCode = 'route_search_limit';
    configureApiBase(Uri.parse('https://route-error.example.test'));
    ApiClient.httpClient = MockClient((request) async {
      expect(request.url.path, '/route');
      requests.add(jsonDecode(request.body) as Map<String, dynamic>);
      return http.Response(jsonEncode({
        'detail': {'code': errorCode, 'message': rawMessage, 'diagnostic': diagnostic},
      }), 503, headers: {'content-type': 'application/json; charset=utf-8'});
    });
  });

  tearDown(() => ApiClient.httpClient = originalClient);

  ProviderContainer prepare({String preference = 'fewTransfers'}) {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final notifier = container.read(routeSearchProvider.notifier);
    notifier.setFrom('35.69,139.78', name: '始点');
    notifier.setTo('35.71,139.80', name: '終点');
    notifier.setPref(preference);
    notifier.setBusOnly(true);
    notifier.setStartTime(DateTime(2099, 10, 12, 10));
    return container;
  }

  Future<void> showNotice(
    WidgetTester tester,
    ProviderContainer container,
    Locale locale, {
    double textScale = 1,
  }) async {
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: CupertinoApp(
        locale: locale,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
        home: const CupertinoPageScaffold(
          child: CustomScrollView(slivers: [
            SliverFillRemaining(hasScrollBody: false, child: RouteSearchErrorNotice()),
          ]),
        ),
      ),
    ));
    await tester.pumpAndSettle();
  }

  test('a stopped search retains its original exception and stack until criteria change', () async {
    final error = StateError('original route failure');
    final stack = StackTrace.fromString('original route stack');
    final service = _OriginalFailureService(error, stack);
    final notifier = RouteSearchNotifier(service);
    addTearDown(notifier.dispose);
    notifier.setFrom('35.69,139.78');
    notifier.setTo('35.71,139.80');
    await notifier.triggerSearch();

    expect(notifier.state.error, same(error));
    expect(notifier.state.errorStackTrace.toString(), contains('original route stack'));
    expect(notifier.state.errorMessage, error.toString());
    expect(notifier.state.isLoading, isFalse);
    expect(service.calls, 1);
    notifier.setTo('35.72,139.81');
    expect(notifier.state.error, isNull);
    expect(notifier.state.errorStackTrace, isNull);
    expect(notifier.state.errorMessage, isNull);
    expect(service.calls, 1);
  });

  for (final locale in [
    const Locale('ja'), const Locale('en'), const Locale('ko'), const Locale('zh'),
    const Locale.fromSubtags(languageCode: 'zh', scriptCode: 'Hant', countryCode: 'TW'),
  ]) {
    testWidgets('limit notice is localized for $locale and keeps diagnostics out of the screen', (tester) async {
      final container = prepare();
      await container.read(routeSearchProvider.notifier).triggerSearch();
      await showNotice(tester, container, locale);
      final l10n = lookupAppLocalizations(locale);

      expect(find.text(l10n.routeSearchErrorTitle), findsOneWidget);
      expect(find.text(l10n.routeSearchLimitMessage), findsOneWidget);
      expect(find.text(l10n.routeSearchByTime), findsOneWidget);
      for (final raw in ['HTTP 503', 'route_search_limit', 'visited=100001', 'queue=16690']) {
        expect(find.textContaining(raw), findsNothing);
      }
      final state = container.read(routeSearchProvider);
      final error = state.error as ApiException;
      expect(error.statusCode, 503);
      expect(error.code, 'route_search_limit');
      expect(error.diagnostic, diagnostic);
      expect(state.errorMessage, contains(rawMessage));
      expect(state.errorStackTrace, isNotNull);
      expect(state.pref, 'fewTransfers');
      expect(requests, hasLength(1));
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('retry repeats the same request only after a tap', (tester) async {
    final container = prepare();
    await container.read(routeSearchProvider.notifier).triggerSearch();
    await showNotice(tester, container, const Locale('ja'));
    expect(requests, hasLength(1));
    await tester.tap(find.byKey(const ValueKey('route-search-retry')));
    await tester.pumpAndSettle();
    expect(requests, hasLength(2));
    expect(requests.last, requests.first);
    expect(container.read(routeSearchProvider).pref, 'fewTransfers');
  });

  testWidgets('shortest-time action changes only the preference after a tap on a narrow large-text screen', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final container = prepare();
    await container.read(routeSearchProvider.notifier).triggerSearch();
    await showNotice(tester, container, const Locale('ja'), textScale: 2);
    expect(requests, hasLength(1));
    expect(tester.takeException(), isNull);

    final action = find.byKey(const ValueKey('route-search-by-time'));
    await tester.ensureVisible(action);
    await tester.pumpAndSettle();
    await tester.tap(action);
    await tester.pumpAndSettle();
    expect(requests, hasLength(2));
    expect(requests.last, {...requests.first, 'pref': 'time'});
    expect(container.read(routeSearchProvider).pref, 'shortTime');
    expect(find.byKey(const ValueKey('route-search-by-time')), findsNothing);
    expect(tester.takeException(), isNull);
  });

  for (final preference in ['shortTime', 'time']) {
    testWidgets('already using $preference does not suggest the same mode again', (tester) async {
      final container = prepare(preference: preference);
      await container.read(routeSearchProvider.notifier).triggerSearch();
      await showNotice(tester, container, const Locale('ja'));
      expect(find.byKey(const ValueKey('route-search-by-time')), findsNothing);
      expect(find.byKey(const ValueKey('route-search-retry')), findsOneWidget);
      expect(requests, hasLength(1));
    });
  }

  testWidgets('unknown backend errors show a generic explanation and preserve the original details', (tester) async {
    errorCode = 'internal_error';
    final container = prepare();
    await container.read(routeSearchProvider.notifier).triggerSearch();
    await showNotice(tester, container, const Locale('ja'));
    final l10n = lookupAppLocalizations(const Locale('ja'));
    expect(find.text(l10n.routeSearchErrorMessage), findsOneWidget);
    expect(find.textContaining(rawMessage), findsNothing);
    expect(find.byKey(const ValueKey('route-search-by-time')), findsNothing);
    expect((container.read(routeSearchProvider).error as ApiException).diagnostic, diagnostic);
    expect(requests, hasLength(1));
  });
}
