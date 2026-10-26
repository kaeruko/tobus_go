import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/pages/route_detail_page.dart';
import 'package:toeigo/providers/city_profile_provider.dart';
import 'package:toeigo/widgets/estimated_transfer_notice.dart';
import 'package:toeigo/widgets/route_card.dart';

Candidate estimatedCandidate() => Candidate(
  id: 'estimated-transfer-candidate',
  lines: const ['銀座線', '浅草線'],
  linesEn: const ['Ginza Line', 'Asakusa Line'],
  rides: 2,
  boards: 2,
  transfers: 1,
  total: 30,
  totalTime: 30,
  arrivalTime: '10:30',
  containsEstimatedTransfer: true,
  originName: '出発地',
  originNameEn: 'Origin',
  destinationName: '目的地',
  destinationNameEn: 'Destination',
  points: const [],
  steps: [
    StepSeg(
      stepId: 'rail-1',
      kind: 'rail',
      title: '銀座線',
      titleEn: 'Ginza Line',
      fromName: '出発地',
      fromNameEn: 'Origin',
      toName: '駅A',
      toNameEn: 'Station A',
      departureTime: '10:00',
      arrivalTime: '10:05',
      stops: [
        StopPoint(
          name: '出発地',
          nameEn: 'Origin',
          point: const LatLng(35.0, 139.0),
          stopId: 'tokyo_metro:origin',
        ),
        StopPoint(
          name: '駅A',
          nameEn: 'Station A',
          point: const LatLng(35.1, 139.1),
          stopId: 'tokyo_metro:a',
        ),
      ],
    ),
    StepSeg(
      stepId: 'estimated-walk',
      kind: 'walk',
      title: '徒歩',
      titleEn: 'Walk',
      fromName: '駅A',
      fromNameEn: 'Station A',
      toName: '駅B',
      toNameEn: 'Station B',
      minutes: 15,
      meters: 0,
      planningDetails: const {
        'physical_walk_meters': null,
        'planning_walk_resource_meters': 600,
        'walking_time_basis': 'app_conservative_allowance',
      },
    ),
    StepSeg(
      stepId: 'rail-2',
      kind: 'rail',
      title: '浅草線',
      titleEn: 'Asakusa Line',
      fromName: '駅B',
      fromNameEn: 'Station B',
      toName: '目的地',
      toNameEn: 'Destination',
      departureTime: '10:20',
      arrivalTime: '10:30',
      stops: [
        StopPoint(
          name: '駅B',
          nameEn: 'Station B',
          point: const LatLng(35.2, 139.2),
          stopId: 'tokyo_metro:b',
        ),
        StopPoint(
          name: '目的地',
          nameEn: 'Destination',
          point: const LatLng(35.3, 139.3),
          stopId: 'tokyo_metro:destination',
        ),
      ],
    ),
  ],
);

Widget localizedApp(Locale locale, Widget child) => ProviderScope(
  child: CupertinoApp(
    locale: locale,
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: CupertinoPageScaffold(child: child),
  ),
);

void main() {
  test('estimated marker survives saved-route serialization', () {
    final restored = Candidate.fromJson(estimatedCandidate().toJson());

    expect(restored.containsEstimatedTransfer, isTrue);
  });

  final translations = <Locale, List<String>>{
    const Locale('ja'): ['推定乗換を含む経路', '乗換時間にはアプリによる15分の推定値を使用しています。'],
    const Locale('en'): [
      'Route with estimated transfers',
      'The app assumes 15 minutes for the transfer.',
    ],
    const Locale('zh'): ['包含推测换乘的路线', '应用将换乘时间假定为15分钟。'],
    const Locale.fromSubtags(
      languageCode: 'zh',
      scriptCode: 'Hant',
      countryCode: 'TW',
    ): [
      '包含推估轉乘的路線',
      '應用程式將轉乘時間假定為15分鐘。',
    ],
    const Locale('ko'): ['추정 환승이 포함된 경로', '앱은 환승 시간으로 15분을 가정합니다.'],
  };

  for (final entry in translations.entries) {
    testWidgets('estimated warning is explicit in ${entry.key}', (
      tester,
    ) async {
      await tester.pumpWidget(
        localizedApp(entry.key, const EstimatedTransferWarning()),
      );

      expect(find.text(entry.value[0]), findsOneWidget);
      expect(find.textContaining(entry.value[1]), findsOneWidget);
      expect(find.textContaining('600m'), findsNothing);
    });

    testWidgets(
      'estimated copy wraps on a 320dp screen at 130% text in ${entry.key}',
      (tester) async {
        tester.view.physicalSize = const Size(320, 568);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);

        await tester.pumpWidget(
          localizedApp(
            entry.key,
            MediaQuery(
              data: const MediaQueryData(
                size: Size(320, 568),
                textScaler: TextScaler.linear(1.3),
              ),
              child: SingleChildScrollView(
                child: Column(
                  children: [
                    EstimatedTransferSearchControl(
                      value: true,
                      onChanged: (_) {},
                    ),
                    const SizedBox(height: 12),
                    const EstimatedTransferWarning(),
                  ],
                ),
              ),
            ),
          ),
        );

        expect(find.text(entry.value[0]), findsOneWidget);
        expect(find.textContaining(entry.value[1]), findsNWidgets(2));
        expect(find.textContaining('600m'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('search control changes only through its explicit switch', (
    tester,
  ) async {
    bool? selected;
    await tester.pumpWidget(
      localizedApp(
        const Locale('ja'),
        EstimatedTransferSearchControl(
          value: false,
          onChanged: (value) => selected = value,
        ),
      ),
    );

    expect(find.text('推定乗換を含む経路も表示'), findsOneWidget);
    expect(
      find.byKey(const Key('estimated-transfer-option-description')),
      findsNothing,
    );
    await tester.tap(find.byKey(const Key('estimated-transfer-option-switch')));
    expect(selected, isTrue);
  });

  testWidgets('estimated candidate is labelled on the result card', (
    tester,
  ) async {
    await tester.pumpWidget(
      localizedApp(
        const Locale('ja'),
        RouteCard(candidate: estimatedCandidate(), rank: 1),
      ),
    );

    expect(find.text('推定乗換を含む経路'), findsOneWidget);
    expect(find.textContaining('実際の通路・徒歩距離'), findsOneWidget);
    expect(find.textContaining('600m'), findsNothing);
  });

  testWidgets('estimated candidate is labelled on route detail', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [cityProfileProvider.overrideWithValue(sendaiCityProfile)],
        child: CupertinoApp(
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: RouteDetailPage(candidate: estimatedCandidate()),
        ),
      ),
    );

    expect(find.text('Route with estimated transfers'), findsOneWidget);
    expect(find.textContaining('walking route, distance'), findsOneWidget);
    expect(find.textContaining('600m'), findsNothing);
  });
}
