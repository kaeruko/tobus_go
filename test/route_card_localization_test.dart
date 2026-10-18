import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/route_card.dart';

void main() {
  final candidate = Candidate(
    id: 'route-card-wait-en',
    lines: const ['上23'],
    linesEn: const ['Ueno-Matsuzakaya'],
    rides: 1,
    boards: 1,
    transfers: 0,
    total: 64,
    totalTime: 64,
    arrivalTime: '11:33',
    points: const [],
    originName: '押上',
    originNameEn: 'Oshiage',
    destinationName: '上野',
    destinationNameEn: 'Ueno',
    steps: [
      StepSeg(
        stepId: 'wait-1',
        kind: 'wait',
        title: '待ち時間',
        titleEn: 'Wait',
        fromName: '押上',
        fromNameEn: 'Oshiage',
        toName: '押上',
        toNameEn: 'Oshiage',
        place: '押上',
        placeEn: 'Oshiage',
        minutes: 38,
      ),
      StepSeg(
        stepId: 'walk-1',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '押上',
        fromNameEn: 'Oshiage',
        toName: '押上駅前',
        toNameEn: 'Oshiage Sta.',
        minutes: 7,
        meters: 556,
      ),
      StepSeg(
        stepId: 'bus-1',
        kind: 'bus',
        title: '上23 上野松坂屋前行',
        titleEn: 'Ueno-Matsuzakaya',
        fromName: '押上駅前',
        fromNameEn: 'Oshiage Sta.',
        toName: '上野松坂屋前',
        toNameEn: 'Ueno-Matsuzakaya',
        minutes: 19,
      ),
    ],
  );

  Future<void> pumpCard(
    WidgetTester tester,
    Locale locale, {
    bool showRank = true,
    Widget? titleTrailing,
    Candidate? route,
  }) async {
    await tester.pumpWidget(
      ProviderScope(
        child: CupertinoApp(
          locale: locale,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CupertinoPageScaffold(
            child: RouteCard(
              candidate: route ?? candidate,
              rank: 1,
              showRank: showRank,
              titleTrailing: titleTrailing,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('saved-route style card can hide candidate rank', (tester) async {
    await pumpCard(
      tester,
      const Locale('en'),
      showRank: false,
    );

    expect(find.text('C1'), findsNothing);
    expect(find.text('Ueno-Matsuzakaya'), findsOneWidget);
  });

  testWidgets('route card can show an interactive title trailing control', (
    tester,
  ) async {
    var tapped = false;
    await pumpCard(
      tester,
      const Locale('ja'),
      showRank: false,
      titleTrailing: CupertinoButton(
        key: const ValueKey('memo-title-action'),
        padding: EdgeInsets.zero,
        onPressed: () => tapped = true,
        child: const Text('📝'),
      ),
    );

    expect(find.text('上23'), findsOneWidget);
    expect(find.text('📝'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('memo-title-action')));
    expect(tapped, isTrue);
  });

  testWidgets('Japanese route card shows destination arrival, not duration', (
    tester,
  ) async {
    await pumpCard(tester, const Locale('ja'));

    expect(find.text('11:33着'), findsOneWidget);
    expect(find.text('所要 64分'), findsNothing);
  });

  testWidgets('English route card shows destination arrival, not duration', (
    tester,
  ) async {
    await pumpCard(tester, const Locale('en'));

    expect(find.text('Arrive 11:33'), findsOneWidget);
    expect(find.text('64 min'), findsNothing);
  });

  testWidgets('route card uses provided arrival even when it is after midnight', (
    tester,
  ) async {
    final overnight = Candidate.fromJson({
      ...candidate.toJson(),
      'arrival_time': '00:05',
    });
    await pumpCard(tester, const Locale('ja'), route: overnight);

    expect(find.text('00:05着'), findsOneWidget);
    expect(find.text('11:33着'), findsNothing);
  });

  testWidgets('route card clearly reports missing arrival time', (
    tester,
  ) async {
    final missingArrival = Candidate.fromJson({
      ...candidate.toJson(),
      'arrival_time': null,
    });
    await pumpCard(tester, const Locale('ja'), route: missingArrival);

    expect(find.text('時刻不明'), findsOneWidget);
    expect(find.text('所要 64分'), findsNothing);
  });

  testWidgets('English route card localizes wait summary', (tester) async {
    await pumpCard(tester, const Locale('en'));

    expect(find.textContaining('Wait (about 38 min)'), findsOneWidget);
    expect(find.textContaining('待ち時間'), findsNothing);
  });

  testWidgets('Japanese route card keeps Japanese wait summary', (tester) async {
    await pumpCard(tester, const Locale('ja'));

    expect(find.textContaining('待ち時間（約38分）'), findsOneWidget);
  });

  testWidgets('English route card localizes current location', (tester) async {
    final currentLocationCandidate = Candidate(
      id: 'current-location-en',
      lines: const ['上23'],
      linesEn: const ['Ueno-Matsuzakaya'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 49,
      totalTime: 49,
      points: const [],
      originName: '現在地',
      originNameEn: 'Current location',
      destinationName: '上野駅',
      destinationNameEn: 'Ueno Station',
      steps: [
        StepSeg(
          stepId: 'walk-origin',
          kind: 'walk',
          title: '徒歩',
          titleEn: 'Walk',
          fromName: '現在地',
          fromNameEn: 'Current location',
          toName: '平井七丁目',
          toNameEn: 'Hirai-nanachome',
          minutes: 3,
          meters: 213,
        ),
        StepSeg(
          stepId: 'bus-1',
          kind: 'bus',
          title: '上23 上野松坂屋前行',
          titleEn: 'Ueno-Matsuzakaya',
          fromName: '平井七丁目',
          fromNameEn: 'Hirai-nanachome',
          toName: '上野松坂屋前',
          toNameEn: 'Ueno-Matsuzakaya',
          minutes: 45,
          edges: 23,
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        child: CupertinoApp(
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CupertinoPageScaffold(
            child: RouteCard(
              candidate: currentLocationCandidate,
              rank: 1,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.textContaining('Current location (現在地) → Ueno Station (上野駅)'),
      findsOneWidget,
    );
  });

  testWidgets('common route card does not render development notices or unknown metres', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final planned = Candidate(
      planningNotice: 'development notice must remain internal',
      id: 'route-card-planned',
      lines: const ['上23'],
      linesEn: const ['Ueno-Matsuzakaya'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 25,
      totalTime: 25,
      arrivalTime: '11:33',
      points: const [],
      walkingDistanceMeters: 0,
      walkingSegmentCount: 1,
      originName: '押上',
      originNameEn: 'Oshiage',
      destinationName: '上野',
      destinationNameEn: 'Ueno',
      steps: [
        StepSeg(
          stepId: 'walk-unverified',
          kind: 'walk',
          title: '地点からの徒歩（推定）',
          minutes: 3,
          meters: 0,
          planningDetails: {
            'physical_walk_meters': null,
            'notice': 'internal walk provenance',
          },
        ),
        StepSeg(
          stepId: 'bus-planned',
          kind: 'bus',
          title: '上23 上野松坂屋前行',
          titleEn: 'Ueno-Matsuzakaya',
          fromName: '押上駅前',
          fromNameEn: 'Oshiage Sta.',
          toName: '上野松坂屋前',
          toNameEn: 'Ueno-Matsuzakaya',
          minutes: 20,
        ),
      ],
    );
    expect(planned.hasUnknownWalkingDistance, isTrue);
    await pumpCard(tester, const Locale('ja'), route: planned);
    expect(find.text('11:33着'), findsOneWidget);
    expect(find.text('徒歩'), findsOneWidget);
    expect(find.textContaining('到着目安'), findsNothing);
    expect(find.textContaining('development notice'), findsNothing);
    expect(find.textContaining('internal walk provenance'), findsNothing);
    expect(find.textContaining('0m'), findsNothing);
    expect(tester.takeException(), isNull);
    await pumpCard(tester, const Locale('en'), route: planned);
    expect(find.text('Arrive 11:33'), findsOneWidget);
    expect(find.textContaining('到着目安'), findsNothing);
    expect(tester.takeException(), isNull);

    // Geometry-derived metres are still displayable even when the physical
    // walking path has not been verified by the source.
    final geometric = Candidate.fromJson({
      ...planned.toJson(),
      'walking_distance_meters': 124,
      'steps': [
        {...planned.steps.first.toJson(), 'meters': 124},
        planned.steps.last.toJson(),
      ],
    });
    expect(geometric.hasUnknownWalkingDistance, isFalse);
    await pumpCard(tester, const Locale('ja'), route: geometric);
    expect(find.text('徒歩 124m'), findsOneWidget);
    expect(find.text('11:33着'), findsOneWidget);
    expect(find.textContaining('到着目安'), findsNothing);
    expect(tester.takeException(), isNull);
  });

}
