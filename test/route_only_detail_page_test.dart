import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/pages/route_detail_page.dart';
import 'package:toeigo/providers/city_profile_provider.dart';
import 'package:toeigo/providers/navigation_provider.dart';
import 'package:toeigo/providers/route_search_provider.dart';

void main() {
  testWidgets('Yokohama uses shared detail and exposes realtime action', (
    tester,
  ) async {
    final candidate = Candidate(
      id: 'candidate-1',
      lines: const ['8'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 15,
      totalTime: 15,
      steps: [
        StepSeg(
          stepId: 'bus-1',
          kind: 'bus',
          title: '8系統',
          fromName: '横浜駅前',
          toName: '山下公園前',
          routeId: 'yokohama_bus:R1',
          tripId: 'yokohama_bus:T1',
        ),
      ],
      points: const [],
      arrivalTime: '10:15',
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [cityProfileProvider.overrideWithValue(yokohamaCityProfile)],
        child: CupertinoApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: RouteDetailPage(candidate: candidate),
        ),
      ),
    );

    expect(find.text('この経路で行く'), findsOneWidget);
    expect(find.text('所要時間'), findsOneWidget);
    expect(find.text('乗車区間'), findsOneWidget);
    expect(find.text('8系統'), findsOneWidget);
    expect(find.byIcon(CupertinoIcons.bookmark), findsNothing);
    expect(find.text('My Routeに追加'), findsNothing);
  });
  testWidgets('Yokohama route detail renders English labels', (tester) async {
    final candidate = Candidate(
      id: 'candidate-en',
      lines: const ['8'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 15,
      totalTime: 15,
      steps: [
        StepSeg(
          stepId: 'bus-1',
          kind: 'bus',
          title: '8系統',
          titleEn: 'Route 8',
          fromName: '横浜駅前',
          fromNameEn: 'Yokohama Station',
          toName: '山下公園前',
          toNameEn: 'Yamashita Park',
          routeId: 'yokohama_bus:R1',
          tripId: 'yokohama_bus:T1',
        ),
      ],
      points: const [],
      arrivalTime: '10:15',
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [cityProfileProvider.overrideWithValue(yokohamaCityProfile)],
        child: CupertinoApp(
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: RouteDetailPage(candidate: candidate),
        ),
      ),
    );

    expect(find.text('Start this route'), findsOneWidget);
    expect(find.text('Duration'), findsOneWidget);
    expect(find.text('Ride segments'), findsOneWidget);
    expect(find.text('Route 8'), findsNWidgets(2));
    expect(
      find.text(
        'Yokohama Station (横浜駅前) → Yamashita Park (山下公園前)',
      ),
      findsOneWidget,
    );
  });
  testWidgets('saved route CTA seeds Search without starting a trip', (
    tester,
  ) async {
    final candidate = Candidate(
      id: 'saved-route',
      lines: const ['浅草線'],
      linesEn: const ['Asakusa Line'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 10,
      totalTime: 10,
      steps: [
        StepSeg(
          stepId: 'rail-saved',
          kind: 'rail',
          title: '浅草線',
          titleEn: 'Asakusa Line',
          fromName: '押上',
          fromNameEn: 'Oshiage',
          toName: '蔵前',
          toNameEn: 'Kuramae',
          departureTime: '12:00',
          arrivalTime: '12:10',
        ),
      ],
      points: const [
        LatLng(35.7101, 139.8107),
        LatLng(35.7033, 139.7908),
      ],
      originCoords: const LatLng(35.7101, 139.8107),
      destinationCoords: const LatLng(35.7033, 139.7908),
      originName: '押上',
      originNameEn: 'Oshiage',
      destinationName: '蔵前',
      destinationNameEn: 'Kuramae',
      preference: 'fewTransfers',
      arrivalTime: '12:10',
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [cityProfileProvider.overrideWithValue(tokyoCityProfile)],
        child: CupertinoApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: RouteDetailPage(
            candidate: candidate,
            fromSavedRoute: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('この経路でおでかけ'), findsOneWidget);
    expect(find.text('この経路で行く'), findsNothing);
    expect(find.text('My Routeに追加'), findsOneWidget);

    final planButton = find.text('この経路でおでかけ');
    await tester.ensureVisible(planButton);
    await tester.pumpAndSettle();
    await tester.tap(planButton);
    await tester.pump();

    final context = tester.element(find.byType(RouteDetailPage));
    final container = ProviderScope.containerOf(context);
    final search = container.read(routeSearchProvider);

    expect(search.from, '35.7101,139.8107');
    expect(search.to, '35.7033,139.7908');
    expect(search.fromName, '押上');
    expect(search.toName, '蔵前');
    expect(search.fromNameEn, 'Oshiage');
    expect(search.toNameEn, 'Kuramae');
    expect(search.pref, 'fewTransfers');
    expect(search.startTime, isNotNull);
    expect(search.hasSearched, isFalse);
    expect(container.read(tabIndexProvider), 0);
  });


}
