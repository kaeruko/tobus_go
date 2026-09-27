import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/route_card.dart';
import 'package:toeigo/widgets/route_detail_widgets.dart';

void main() {
  Widget app(Widget child) => ProviderScope(
        child: CupertinoApp(
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CupertinoPageScaffold(
            child: SafeArea(
              child: SingleChildScrollView(child: child),
            ),
          ),
        ),
      );

  StepSeg busStep() => StepSeg(
        stepId: 'bus-middle',
        kind: 'bus',
        title: '008系統',
        titleEn: 'Route 008',
        fromName: '横浜駅前',
        fromNameEn: 'Yokohama Station',
        toName: '山下公園前',
        toNameEn: 'Yamashita Park',
        minutes: 12,
      );

  testWidgets(
    'walk edge names match across card, endpoint summary, and walk detail',
    (tester) async {
      final firstWalk = StepSeg(
        stepId: 'walk-first',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '横浜駅前',
        fromNameEn: 'Yokohama Station',
        toName: '交差点',
        toNameEn: 'Intersection',
        minutes: 3,
        meters: 180,
      );
      final lastWalk = StepSeg(
        stepId: 'walk-last',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '山下公園前',
        fromNameEn: 'Yamashita Park',
        toName: '赤レンガ倉庫入口',
        toNameEn: 'Red Brick Warehouse Entrance',
        minutes: 5,
        meters: 360,
      );
      final candidate = Candidate(
        id: 'walk-edges',
        lines: const ['008系統'],
        linesEn: const ['Route 008'],
        rides: 1,
        boards: 1,
        transfers: 0,
        total: 20,
        totalTime: 20,
        steps: [firstWalk, busStep(), lastWalk],
        points: const [],
      );

      await tester.pumpWidget(
        app(
          Column(
            children: [
              RouteCard(candidate: candidate, rank: 1),
              RouteEndpointSummary(candidate: candidate),
              RouteStepTile(segment: firstWalk),
              RouteStepTile(segment: lastWalk),
            ],
          ),
        ),
      );
      await tester.pumpAndSettle();

      final card = find.byType(RouteCard);
      final summary = find.byType(RouteEndpointSummary);

      expect(
        find.descendant(
          of: card,
          matching: find.text(
            'Yokohama Station (横浜駅前) → '
            'Red Brick Warehouse Entrance (赤レンガ倉庫入口)',
          ),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: summary,
          matching: find.text('Yokohama Station (横浜駅前)'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: summary,
          matching: find.text(
            'Red Brick Warehouse Entrance (赤レンガ倉庫入口)',
          ),
        ),
        findsOneWidget,
      );
      expect(
        find.text(
          'Yokohama Station (横浜駅前) → Intersection (交差点)',
        ),
        findsOneWidget,
      );
      expect(
        find.text(
          'Yamashita Park (山下公園前) → '
          'Red Brick Warehouse Entrance (赤レンガ倉庫入口)',
        ),
        findsOneWidget,
      );
      expect(find.text('Station'), findsNothing);
    },
  );

  testWidgets(
    'leading wait name matches card, endpoint summary, and wait detail',
    (tester) async {
      final wait = StepSeg(
        stepId: 'wait-first',
        kind: 'wait',
        title: '待ち時間',
        titleEn: 'Wait',
        fromName: '横浜駅前',
        fromNameEn: 'Yokohama Station',
        toName: '横浜駅前',
        toNameEn: 'Yokohama Station',
        place: '横浜駅前',
        placeEn: 'Yokohama Station',
        minutes: 2,
      );
      final lastWalk = StepSeg(
        stepId: 'walk-last',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '山下公園前',
        fromNameEn: 'Yamashita Park',
        toName: '赤レンガ倉庫入口',
        toNameEn: 'Red Brick Warehouse Entrance',
        minutes: 5,
        meters: 360,
      );
      final candidate = Candidate(
        id: 'wait-edge',
        lines: const ['008系統'],
        linesEn: const ['Route 008'],
        rides: 1,
        boards: 1,
        transfers: 0,
        total: 19,
        totalTime: 19,
        steps: [wait, busStep(), lastWalk],
        points: const [],
      );

      await tester.pumpWidget(
        app(
          Column(
            children: [
              RouteCard(candidate: candidate, rank: 1),
              RouteEndpointSummary(candidate: candidate),
              RouteStepTile(segment: wait),
            ],
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        find.descendant(
          of: find.byType(RouteCard),
          matching: find.text(
            'Yokohama Station (横浜駅前) → '
            'Red Brick Warehouse Entrance (赤レンガ倉庫入口)',
          ),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byType(RouteEndpointSummary),
          matching: find.text('Yokohama Station (横浜駅前)'),
        ),
        findsOneWidget,
      );
      expect(
        find.text('Wait at Yokohama Station (横浜駅前)'),
        findsOneWidget,
      );
    },
  );
}
