import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/explore_models.dart';
import 'package:toeigo/pages/explore_page.dart';
import 'package:toeigo/providers/explore_provider.dart';
import 'package:toeigo/providers/location_provider.dart';

class _ExploreNotifier extends ExploreNotifier {}

Position _position() => Position(
      latitude: 35.6812,
      longitude: 139.7671,
      timestamp: DateTime(2026, 9, 28),
      accuracy: 1,
      altitude: 0,
      heading: 0,
      speed: 0,
      speedAccuracy: 0,
      altitudeAccuracy: 0,
      headingAccuracy: 0,
    );

Widget _app(Locale locale) {
  return ProviderScope(
    overrides: [
      exploreProvider.overrideWith((ref) => _ExploreNotifier()),
      exploreEditorialContentProvider.overrideWith(
        (ref) async => ExploreEditorialContent(byStopId: const {}),
      ),
      locationStreamProvider.overrideWith((ref) => Stream.value(_position())),
    ],
    child: MaterialApp(
      locale: locale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: const ExplorePage(),
    ),
  );
}

void main() {
  testWidgets('Explore initial screen is localized in English', (tester) async {
    await tester.pumpWidget(_app(const Locale('en')));
    await tester.pumpAndSettle();

    expect(find.text('Find places with no transfers'), findsOneWidget);
    expect(find.text('Explore nearby'), findsOneWidget);
    expect(find.text('Tap the button to start searching.'), findsOneWidget);
    expect(find.text('一本で行ける場所を探す'), findsNothing);
    expect(find.text('周辺を探索する'), findsNothing);
  });

  testWidgets('Explore initial screen keeps Japanese copy in Japanese',
      (tester) async {
    await tester.pumpWidget(_app(const Locale('ja')));
    await tester.pumpAndSettle();

    expect(find.text('一本で行ける場所を探す'), findsOneWidget);
    expect(find.text('周辺を探索する'), findsOneWidget);
    expect(find.text('ボタンを押して検索を開始してください'), findsOneWidget);
  });
}
