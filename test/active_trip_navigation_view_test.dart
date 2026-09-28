import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/widgets/active_trip_navigation_view.dart';
import 'package:toeigo/widgets/app_navigation_bar.dart';

void main() {
  testWidgets('移動中ヘッダーはブランド画像と経路名を表示できる', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          appBar: AppBar(
            title: ActiveTripAppBarTitle(
              appName: 'Toei GO',
              tripTitle: 'Current location → Ueno Station',
              brand: cityBrandNavigationTitle(
                city: AppCity.tokyo,
                fallbackTitle: 'Toei GO',
              ),
            ),
          ),
        ),
      ),
    );

    expect(find.text('Toei GO'), findsNothing);
    expect(find.text('Current location → Ueno Station'), findsOneWidget);
    final image = tester.widget<Image>(find.byType(Image));
    expect((image.image as AssetImage).assetName, 'assets/icon/tokyo_en.png');
  });

  testWidgets('大きいstatusカードを出さずmode固有slotを配置する', (tester) async {
    final busStep = StepSeg(
      stepId: 'bus-1',
      kind: 'bus',
      title: '上23',
      fromName: '浅草',
      toName: '平井駅前',
    );
    final navState = NavigationState(
      mainText: '上23 乗車中',
      subText: '浅草',
      color: Colors.green,
      statusLabel: '🚌乗車中',
      remainingStops: 2,
      currentStepId: busStep.stepId,
      step: busStep,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: ActiveTripNavigationView(
          navState: navState,
          tripTitle: 'テスト移動',
          appBar: AppBar(title: const Text('共通ナビ')),
          onTapStops: () {},
          statusHeaderTrailing: const Text('09:30'),
          beforeScheduleSections: const [Text('遅延セクション')],
          scheduleSection: const Text('予定ウィンドウ'),
          afterScheduleSections: const [Text('モード固有操作')],
          bottomNavigationBar: const Text('下部操作'),
        ),
      ),
    );

    expect(find.text('共通ナビ'), findsOneWidget);
    expect(find.text('09:30'), findsOneWidget);
    expect(find.text('遅延セクション'), findsOneWidget);
    expect(find.text('予定ウィンドウ'), findsOneWidget);
    expect(find.text('モード固有操作'), findsOneWidget);
    expect(find.text('下部操作'), findsOneWidget);
    expect(find.text('上23 乗車中'), findsNothing);
    expect(find.text('🚌乗車中'), findsNothing);
    expect(find.text('テスト移動'), findsNothing);
  });

  testWidgets('roleを知らず空のtripTitleはfail-fastする', (tester) async {
    final navState = const NavigationState(
      mainText: '徒歩',
      subText: '移動中',
      color: Colors.white,
      statusLabel: '徒歩',
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: ActiveTripNavigationView(
          navState: navState,
          tripTitle: '   ',
          appBar: AppBar(),
          onTapStops: () {},
          scheduleSection: const Text('予定'),
        ),
      ),
    );

    final error = tester.takeException();
    expect(error, isA<StateError>());
    expect(error.toString(), contains('tripTitleが空'));
  });
  testWidgets('現在地と目的地を大きい経路カードで表示できる', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Padding(
            padding: EdgeInsets.all(16),
            child: ActiveTripEndpointCard(
              currentLabel: '現在地',
              currentPlace: '平井七丁目第三アパート前',
              destinationLabel: '目的地',
              destinationPlace: '上野松坂屋前',
            ),
          ),
        ),
      ),
    );

    expect(find.text('現在地'), findsOneWidget);
    expect(find.text('平井七丁目第三アパート前'), findsOneWidget);
    expect(find.text('目的地'), findsOneWidget);
    expect(find.text('上野松坂屋前'), findsOneWidget);
    expect(find.byIcon(Icons.arrow_right_alt_rounded), findsOneWidget);
    expect(find.byIcon(Icons.location_on), findsNWidgets(2));
    expect(tester.takeException(), isNull);
  });

  testWidgets('現在地・目的地カードは空文字をfail-fastする', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: ActiveTripEndpointCard(
            currentLabel: '現在地',
            currentPlace: ' ',
            destinationLabel: '目的地',
            destinationPlace: '上野松坂屋前',
          ),
        ),
      ),
    );

    final error = tester.takeException();
    expect(error, isA<StateError>());
    expect(error.toString(), contains('空の表示値'));
  });


}
