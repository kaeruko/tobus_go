import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/providers/locale_provider.dart';
import 'package:toeigo/widgets/language_settings_section.dart';
import 'package:toeigo/widgets/place_field.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('language preference survives restart and can return to system', () async {
    var container = ProviderContainer();
    expect(await container.read(localeProvider.future), isNull);
    await container.read(localeProvider.notifier).setLocale(const Locale('zh'));
    container.dispose();

    container = ProviderContainer();
    addTearDown(container.dispose);
    expect(await container.read(localeProvider.future), const Locale('zh'));
    await container.read(localeProvider.notifier).setLocale(null);
    expect(container.read(localeProvider).valueOrNull, isNull);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.containsKey(LocaleNotifier.preferenceKey), isFalse);
  });

  test('unsupported preferences use device language', () async {
    SharedPreferences.setMockInitialValues({LocaleNotifier.preferenceKey: 'fr'});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    expect(await container.read(localeProvider.future), isNull);
    await expectLater(
      container.read(localeProvider.notifier).setLocale(const Locale('fr')),
      throwsArgumentError,
    );
  });

  test('Chinese device locales resolve to the Simplified Chinese catalog', () {
    for (final locale in [
      const Locale('zh', 'CN'),
      const Locale.fromSubtags(languageCode: 'zh', scriptCode: 'Hans'),
    ]) {
      expect(
        basicLocaleListResolution([locale], AppLocalizations.supportedLocales),
        const Locale('zh'),
      );
    }
  });

  testWidgets('switching languages preserves fields without more API requests',
      (tester) async {
    final originalClient = ApiClient.httpClient;
    final requests = <String>[];
    configureApiBase(Uri.parse('https://api.example.test'));
    ApiClient.resetWarmUpForTesting();
    ApiClient.httpClient = MockClient((request) async {
      requests.add(request.url.path);
      return http.Response('{"status":"ready","city":"tokyo"}', 200);
    });
    addTearDown(() {
      ApiClient.httpClient = originalClient;
      ApiClient.resetWarmUpForTesting();
    });

    final container = ProviderContainer();
    addTearDown(container.dispose);
    await container.read(localeProvider.future);
    await container.read(localeProvider.notifier).setLocale(const Locale('ja'));
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: Consumer(builder: (context, ref, child) {
        return CupertinoApp(
          locale: ref.watch(localeProvider).valueOrNull,
          supportedLocales: AppLocalizations.supportedLocales,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          home: CupertinoPageScaffold(
            child: SafeArea(child: Column(children: [
              const LanguageSettingsSection(),
              PlaceField(
                label: 'Destination',
                value: '35.0,139.0',
                displayValue: 'Tokyo',
                onChanged: (_, _) {},
              ),
            ])),
          ),
        );
      }),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('简体中文'));
    await tester.pumpAndSettle();
    expect(find.text('语言'), findsOneWidget);
    expect(find.text('Tokyo'), findsOneWidget);
    expect(container.read(localeProvider).valueOrNull, const Locale('zh'));
    await tester.tap(find.text('English'));
    await tester.pumpAndSettle();
    expect(find.text('Language'), findsOneWidget);
    expect(requests, ['/warmup']);
    expect(tester.takeException(), isNull);
  });
}
