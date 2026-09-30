import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/rail_progress.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/trip_navigation_status_card.dart';

void main() {
  testWidgets('compact inline status hides generic waiting heading', (
    tester,
  ) async {
    final step = StepSeg(
      stepId: 'bus-waiting',
      kind: 'bus',
      title: '錦37',
      fromName: '十間橋通り',
      toName: '押上駅前',
    );
    final navigation = NavigationState(
      mainText: '待機中',
      subText: '十間橋通り 📍',
      color: Colors.blue,
      statusLabel: '乗車待ち',
      mainTextToken: const NavigationTextToken(
        NavigationTextKey.busWaitingMain,
      ),
      subTextToken: const NavigationTextToken(
        NavigationTextKey.busPositionCheckingAtStopSub,
        {'stopName': '十間橋通り'},
      ),
      noticeText: '📍',
      noticeTextToken: const NavigationTextToken(
        NavigationTextKey.realtimeUnavailableNotice,
      ),
      step: step,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationInlineStatus(
            navState: navigation,
            onTapStops: () {},
          ),
        ),
      ),
    );

    expect(find.text('待機中'), findsNothing);
    expect(find.text('乗車待ち'), findsNothing);
    expect(find.text('十間橋通り 📍'), findsOneWidget);
    expect(find.text('📍'), findsOneWidget);
  });

  testWidgets('bus and rail remaining counts use transport-specific wording', (
    tester,
  ) async {
    Future<void> pumpCard({
      required String kind,
      required int remainingStops,
    }) async {
      final step = StepSeg(
        stepId: 'ride-step',
        kind: kind,
        title: kind == 'bus' ? '上23' : '浅草線',
        fromName: '乗車地点',
        toName: '降車地点',
      );
      final navigation = NavigationState(
        mainText: '移動中',
        subText: '降車地点で降ります',
        color: Colors.blue,
        statusLabel: '乗車中',
        remainingStops: remainingStops,
        nextStopName: '次の駅',
        step: step,
      );

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: TripNavigationStatusCard(
              navState: navigation,
              tripTitle: '出発地 → 目的地',
              onTapStops: () {},
            ),
          ),
        ),
      );
    }

    await pumpCard(kind: 'bus', remainingStops: 2);
    expect(find.text('のこり 2 回停車'), findsOneWidget);
    expect(find.text('次: 次の駅'), findsOneWidget);

    await pumpCard(kind: 'rail', remainingStops: 3);
    expect(find.text('のこり 3 駅'), findsOneWidget);
    expect(find.text('のこり 2 回停車'), findsNothing);
  });
  testWidgets(
    'departure countdown separates time countdown and next boarding',
    (tester) async {
      tester.view.physicalSize = const Size(320, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      final navigation = NavigationState(
        mainText: '6:28 出発　あと13分',
        subText: '6:31 上23 上野松坂屋前行 乗車',
        color: Colors.blue,
        statusLabel: '待機',
        mainTextToken: const NavigationTextToken(
          NavigationTextKey.departureCountdownMain,
          {'leaveTime': '6:28', 'minutes': 13},
        ),
        subTextToken:
            const NavigationTextToken(NavigationTextKey.boardingSub, {
              'rideTime': '6:31',
              'routeTitle': '上23 上野松坂屋前行',
              'routeTitleEn': '上23 · Ueno-Matsuzakaya',
            }),
        statusLabelToken: const NavigationTextToken(
          NavigationTextKey.waitingStatus,
        ),
        isMoving: false,
      );

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: TripNavigationStatusCard(
              navState: navigation,
              tripTitle: '現在地 → 東墨田１丁目',
              onTapStops: () {},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('departure-countdown-heading')),
        findsOneWidget,
      );
      expect(find.byIcon(Icons.schedule), findsOneWidget);
      expect(find.text('6:28'), findsOneWidget);
      expect(find.text('あと13分'), findsOneWidget);
      expect(find.text('6:31'), findsOneWidget);
      expect(find.text('上23 上野松坂屋前行'), findsOneWidget);
      expect(find.text('乗車'), findsOneWidget);
      expect(find.text('6:28 出発　あと13分'), findsNothing);
      expect(find.text('6:31 上23 上野松坂屋前行 乗車'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'bus realtime indicator sits beside route title without notice row',
    (tester) async {
      final step = StepSeg(
        stepId: 'bus-realtime-indicator',
        kind: 'bus',
        title: '上23 上野松坂屋前行',
        fromName: '平井七丁目',
        toName: '社会福祉会館前',
        arrivalTime: '19:24',
      );
      final navigation = NavigationState(
        mainText: '上23 上野松坂屋前行 平井七丁目',
        subText: '19:24 社会福祉会館前到着予定',
        color: Colors.blue,
        statusLabel: '🚌乗車中',
        mainTextToken: const NavigationTextToken(
          NavigationTextKey.rideCurrentPlaceMain,
          {'rideTitle': '上23 上野松坂屋前行', 'placeName': '平井七丁目'},
        ),
        subTextToken:
            const NavigationTextToken(NavigationTextKey.rideArrivalSummary, {
              'arrivalTime': '19:24',
              'rideTitle': '上23 上野松坂屋前行',
              'destination': '社会福祉会館前',
            }),
        statusLabelToken: const NavigationTextToken(
          NavigationTextKey.busRideStatus,
        ),
        noticeText: '📍',
        noticeTextToken: const NavigationTextToken(
          NavigationTextKey.realtimeUnavailableNotice,
        ),
        remainingStops: 7,
        nextStopName: '平井七丁目北公園前',
        step: step,
      );

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: TripNavigationStatusCard(
              navState: navigation,
              tripTitle: '現在地 → ベルクス 東墨田店',
              onTapStops: () {},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('上23 上野松坂屋前行'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('ride-realtime-status-indicator')),
        findsOneWidget,
      );
      final semantics = tester.widget<Semantics>(
        find.byKey(const ValueKey('ride-realtime-status-indicator')),
      );
      expect(semantics.properties.label, 'リアルタイム位置情報を更新中');
      expect(find.text('📍'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('English stop labels are localized', (tester) async {
    final step = StepSeg(
      stepId: 'bus-en',
      kind: 'bus',
      title: 'Route 8',
      fromName: 'Origin',
      toName: 'Destination',
    );
    final navigation = NavigationState(
      mainText: 'Moving',
      subText: 'Stay on board',
      color: Colors.blue,
      statusLabel: 'Riding',
      remainingStops: 2,
      nextStopName: '次の停留所',
      nextStopNameEn: 'Next Stop',
      step: step,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Origin → Destination',
            onTapStops: () {},
          ),
        ),
      ),
    );

    expect(find.text('2 stops remaining'), findsOneWidget);
    expect(find.text('Next: Next Stop (次の停留所)'), findsOneWidget);
  });

  testWidgets('generated walk navigation keeps heading and Next bilingual', (
    tester,
  ) async {
    final step = StepSeg(
      stepId: 'walk-en',
      kind: 'walk',
      title: '徒歩',
      titleEn: 'Walk',
      fromName: '交差点',
      fromNameEn: 'Intersection',
      toName: '横浜駅前',
      toNameEn: 'Yokohama Station',
      meters: 420,
    );
    final navigation = NavigationState.navigating(
      step: step,
      busProgress: null,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Walk test',
            onTapStops: () {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Head to Yokohama Station (横浜駅前)'), findsOneWidget);
    expect(find.text('Next: Yokohama Station (横浜駅前)'), findsOneWidget);
  });

  for (final language in ['en', 'zh']) {
    testWidgets(
      '$language walk countdown is rendered as structured transport data',
      (tester) async {
        final locale = Locale(language);
        final l10n = await AppLocalizations.delegate.load(locale);
        tester.view.physicalSize = const Size(320, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });

        final step = StepSeg(
          stepId: 'walk-to-bus',
          kind: 'walk',
          title: '徒歩',
          titleEn: 'Walk',
          fromName: '現在地',
          fromNameEn: 'Current location',
          toName: '平井七丁目',
          toNameEn: 'Hirai-Nanachome',
          minutes: 3,
        );
        final navigation = NavigationState(
          mainText: '9:08 平井七丁目にむかう　あと3分',
          subText: '9:08 上23 乗車',
          color: Colors.blue,
          statusLabel: '移動中',
          mainTextToken: const NavigationTextToken(
            NavigationTextKey.walkToRideCountdownMain,
            {
              'rideTime': '9:08',
              'destination': '平井七丁目',
              'destinationEn': 'Hirai-Nanachome',
              'minutes': 3,
            },
          ),
          subTextToken:
              const NavigationTextToken(NavigationTextKey.boardingSub, {
                'rideTime': '9:08',
                'routeTitle': '上23・上野松坂屋',
                'routeTitleEn': '上23 · Ueno-Matsuzakaya',
              }),
          statusLabelToken: const NavigationTextToken(
            NavigationTextKey.movingStatus,
          ),
          nextStopName: '平井七丁目',
          nextStopNameEn: 'Hirai-Nanachome',
          currentStepId: step.stepId,
          step: step,
        );

        await tester.pumpWidget(
          MaterialApp(
            locale: locale,
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: Scaffold(
              body: TripNavigationStatusCard(
                navState: navigation,
                tripTitle: 'Current location → Ueno Station',
                onTapStops: () {},
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text(l10n.categoryWalk.toUpperCase()), findsOneWidget);
        expect(find.text(l10n.minutesValue(3)), findsOneWidget);
        expect(find.text('Hirai-Nanachome'), findsOneWidget);
        expect(find.text('平井七丁目'), findsOneWidget);
        expect(find.text('9:08'), findsOneWidget);
        expect(find.text('上23 · Ueno-Matsuzakaya'), findsOneWidget);
        expect(find.text('上23・上野松坂屋'), findsOneWidget);
        expect(
          find.text('Head to Hirai-Nanachome (平井七丁目) for 9:08 · 3 min to go'),
          findsNothing,
        );
        expect(find.text('Next: Hirai-Nanachome (平井七丁目)'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('generic walk navigation may omit optional English destination', (
    tester,
  ) async {
    final step = StepSeg(
      stepId: 'walk-ja-only',
      kind: 'walk',
      title: '徒歩',
      fromName: '入口',
      toName: '公園内広場',
      meters: 120,
    );
    final navigation = NavigationState.navigating(
      step: step,
      busProgress: null,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Walk test',
            onTapStops: () {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Head to 公園内広場'), findsOneWidget);
    expect(find.text('Next: 公園内広場'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('semantic navigation messages render in English', (tester) async {
    final navigation = NavigationState.waitingForDeparture(
      plannedAt: DateTime(2026, 9, 27, 8, 29),
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Tokyo Station → Asakusa',
            onTapStops: () {},
          ),
        ),
      ),
    );

    expect(find.text('Before departure'), findsOneWidget);
    expect(find.text('Departs at 8:29'), findsOneWidget);
    expect(find.text('Not started'), findsOneWidget);
  });

  testWidgets('route arrival heading renders in English', (tester) async {
    final step = StepSeg(
      stepId: 'rail-arrival-en',
      kind: 'rail',
      title: '浅草線',
      titleEn: 'Asakusa Line',
      fromName: '押上',
      fromNameEn: 'Oshiage',
      toName: '蔵前',
      toNameEn: 'Kuramae',
      arrivalTime: '22:13',
    );
    final entry = ScheduleEntry(
      id: 'rail-arrival-entry',
      plannedAt: DateTime(2026, 9, 27, 22, 13),
      label: '🚇浅草線 蔵前に着く',
      itemKind: ScheduleEntryKind.arrival,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: step.stepId,
      routeRole: 'arrival',
    );
    final navigation = NavigationState.fromEntry(
      entry: entry,
      step: step,
      busProgress: null,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Oshiage (押上) → Ueno Station (上野駅)',
            onTapStops: () {},
          ),
        ),
      ),
    );

    expect(find.text('Asakusa Line · Kuramae (蔵前)'), findsOneWidget);
    expect(find.text('You’ve arrived'), findsOneWidget);
    expect(find.text('Arrived'), findsOneWidget);
    expect(find.text('🚇浅草線 蔵前に着く'), findsNothing);
  });

  testWidgets('terminal goal card renders bilingual destination in English', (
    tester,
  ) async {
    final navigation = NavigationState(
      mainText: '上野駅 到着',
      subText: 'お疲れ様でした!',
      color: Colors.orange,
      statusLabel: '到着',
      mainTextToken: const NavigationTextToken(
        NavigationTextKey.goalArrivedMain,
        {'destination': '上野駅', 'destinationEn': 'Ueno Station'},
      ),
      subTextToken: const NavigationTextToken(NavigationTextKey.tripEndedSub),
      statusLabelToken: const NavigationTextToken(
        NavigationTextKey.arrivedStatus,
      ),
      isMoving: false,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Oshiage (押上) → Ueno Station (上野駅)',
            onTapStops: () {},
          ),
        ),
      ),
    );

    expect(find.text('Arrived at Ueno Station (上野駅)'), findsOneWidget);
    expect(find.text('Thanks for traveling with us'), findsOneWidget);
    expect(find.text('Arrived'), findsOneWidget);
    expect(find.text('上野駅 到着'), findsNothing);
    expect(find.text('お疲れ様でした!'), findsNothing);
  });

  for (final language in ['en', 'zh']) {
    testWidgets(
      'structured $language ride display separates long transit names',
      (tester) async {
        final locale = Locale(language);
        final l10n = await AppLocalizations.delegate.load(locale);
        tester.view.physicalSize = const Size(320, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });

        final step = StepSeg(
          stepId: 'rail-en',
          kind: 'rail',
          title: '浅草線',
          titleEn: 'Asakusa Line',
          fromName: '押上',
          fromNameEn: 'Oshiage',
          toName: '蔵前',
          toNameEn: 'Kuramae',
          arrivalTime: '23:10',
        );
        const railProgress = RailProgress(
          stepId: 'rail-en',
          tripId: 'trip-en',
          tripHeadsign: '西馬込',
          tripHeadsignEn: 'Nishi-magome',
          phase: RailProgressPhase.riding,
          boardingSequence: 1,
          destinationSequence: 5,
          lastReachedSequence: 3,
          remainingStops: 2,
          currentStopName: '本所吾妻橋',
          currentStopNameEn: 'Honjo-azumabashi',
          nextStopName: '浅草',
          nextStopNameEn: 'Asakusa',
          currentStatus: 'STOPPED_AT',
        );
        final navigation = NavigationState(
          mainText: '浅草線 西馬込行 本所吾妻橋',
          subText: '23:10 浅草線 西馬込行 蔵前到着予定',
          color: Colors.blue,
          statusLabel: '🚇乗車中',
          mainTextToken: const NavigationTextToken(
            NavigationTextKey.rideCurrentPlaceMain,
            {
              'rideTitle': '浅草線 西馬込行',
              'rideTitleEn': 'Asakusa Line · Nishi-magome',
              'placeName': '本所吾妻橋',
              'placeNameEn': 'Honjo-azumabashi',
            },
          ),
          subTextToken:
              const NavigationTextToken(NavigationTextKey.rideArrivalSummary, {
                'arrivalTime': '23:10',
                'rideTitle': '浅草線 西馬込行',
                'rideTitleEn': 'Asakusa Line · Nishi-magome',
                'destination': '蔵前',
                'destinationEn': 'Kuramae',
              }),
          statusLabelToken: const NavigationTextToken(
            NavigationTextKey.railRideStatus,
          ),
          remainingStops: 2,
          nextStopName: '浅草',
          nextStopNameEn: 'Asakusa',
          railProgress: railProgress,
          step: step,
        );

        await tester.pumpWidget(
          MaterialApp(
            locale: locale,
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: Scaffold(
              body: TripNavigationStatusCard(
                navState: navigation,
                tripTitle: 'Oshiage → Ueno',
                onTapStops: () {},
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Asakusa Line'), findsOneWidget);
        expect(
          find.text(l10n.navRideDirection('Nishi-magome')),
          findsOneWidget,
        );
        expect(find.text('Honjo-azumabashi'), findsOneWidget);
        expect(find.text('(本所吾妻橋)'), findsOneWidget);
        expect(
          find.text(l10n.navCompactRideArrival('23:10', 'Kuramae (蔵前)')),
          findsOneWidget,
        );
        expect(find.text(l10n.nextStop('Asakusa (浅草)')), findsOneWidget);
        expect(
          find.text('Asakusa Line · Nishi-magome · Honjo-azumabashi (本所吾妻橋)'),
          findsNothing,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }
}
