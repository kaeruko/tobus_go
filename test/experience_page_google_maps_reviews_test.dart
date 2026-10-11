import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:url_launcher_platform_interface/link.dart' as launcher_link;
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart'
    as launcher;

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/explore_models.dart';
import 'package:toeigo/pages/experience_page.dart';

class _TestLauncher extends launcher.UrlLauncherPlatform {
  @override
  launcher_link.LinkDelegate? get linkDelegate => null;

  final urls = <Uri>[];
  final modes = <launcher.PreferredLaunchMode>[];
  bool result = true;

  @override
  Future<bool> launchUrl(String url, launcher.LaunchOptions options) async {
    urls.add(Uri.parse(url));
    modes.add(options.mode);
    return result;
  }
}

void main() {
  late _TestLauncher mapsLauncher;

  setUp(() {
    final previous = launcher.UrlLauncherPlatform.instance;
    mapsLauncher = _TestLauncher();
    launcher.UrlLauncherPlatform.instance = mapsLauncher;
    addTearDown(() => launcher.UrlLauncherPlatform.instance = previous);
  });

  Future<void> showEditorial(WidgetTester tester, String language) async {
    final stop = ReachableStop(
      id: 'stop-ueno',
      name: '上野駅前',
      nameEn: 'Ueno Station',
      lat: 35.7138,
      lon: 139.7773,
      viaRoute: 'odpt.Busroute:Toei.Ue23',
    );
    const editorial = ExploreEditorialSpot(
      stopId: 'stop-ueno',
      comment: '雨の上野。',
      commentEn: 'Rainy Ueno.',
      images: [],
    );

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          locale: Locale(language),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: ExperiencePage(stop: stop, editorial: editorial),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  for (final language in ['ja', 'en', 'zh', 'ko']) {
    testWidgets('$language opens nearby Google Maps with no Places call', (
      tester,
    ) async {
      await showEditorial(tester, language);
      expect(find.byKey(const Key('google-maps-nearby-reviews')), findsOneWidget);

      await tester.tap(find.byKey(const Key('google-maps-nearby-reviews')));
      await tester.pumpAndSettle();

      expect(mapsLauncher.urls, hasLength(1));
      expect(mapsLauncher.urls.single.path, '/maps/@');
      expect(mapsLauncher.urls.single.queryParameters, {
        'api': '1',
        'map_action': 'map',
        'center': '35.7138,139.7773',
        'zoom': '16',
      });
      expect(mapsLauncher.modes, [
        launcher.PreferredLaunchMode.externalApplication,
      ]);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('failed open surfaces the error and never retries another URL', (
    tester,
  ) async {
    mapsLauncher.result = false;
    await showEditorial(tester, 'ja');

    await tester.tap(find.byKey(const Key('google-maps-nearby-reviews')));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isA<StateError>());
    expect(find.text('Google Mapsを開けませんでした'), findsOneWidget);
    expect(mapsLauncher.urls, hasLength(1));
    expect(mapsLauncher.modes, [
      launcher.PreferredLaunchMode.externalApplication,
    ]);
  });
}
