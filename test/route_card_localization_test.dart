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
  }) async {
    await tester.pumpWidget(
      ProviderScope(
        child: CupertinoApp(
          locale: locale,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CupertinoPageScaffold(
            child: RouteCard(
              candidate: candidate,
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

}
