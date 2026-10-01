import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/explore_models.dart';
import 'package:toeigo/pages/experience_page.dart';
import 'package:toeigo/providers/explore_provider.dart';

class _FailIfFetchedExploreNotifier extends ExploreNotifier {
  @override
  Future<ExperienceResponse> fetchExperiences(ReachableStop stop) {
    throw StateError('editorial detail must not call /route/experience');
  }
}

void main() {
  testWidgets('editorial detail skips generated experience request', (
    tester,
  ) async {
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
        overrides: [
          exploreProvider.overrideWith(
            (ref) => _FailIfFetchedExploreNotifier(),
          ),
        ],
        child: MaterialApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: ExperiencePage(stop: stop, editorial: editorial),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('みつけるメモ'), findsOneWidget);
    expect(find.text('雨の上野。'), findsOneWidget);
    expect(find.text('周辺のようす'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
