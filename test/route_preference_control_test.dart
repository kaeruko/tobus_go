import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/pages/home_page.dart';
import 'package:toeigo/models/transport_scope.dart';

void main() {
  testWidgets(
    'defers the segmented control until a positive width is available',
    (tester) async {
      var width = 0.0;
      String? selectedValue;
      late StateSetter setTestState;

      await tester.pumpWidget(
        CupertinoApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: StatefulBuilder(
            builder: (context, setState) {
              setTestState = setState;
              return Center(
                child: SizedBox(
                  width: width,
                  child: RoutePreferenceControl(
                    groupValue: selectedValue ?? 'fewTransfers',
                    onValueChanged: (value) {
                      selectedValue = value;
                    },
                  ),
                ),
              );
            },
          ),
        ),
      );

      expect(tester.takeException(), isNull);
      expect(
        find.byType(CupertinoSlidingSegmentedControl<String>),
        findsNothing,
      );

      setTestState(() => width = 320);
      await tester.pump();

      expect(tester.takeException(), isNull);
      expect(
        find.byType(CupertinoSlidingSegmentedControl<String>),
        findsOneWidget,
      );

      await tester.tap(find.text('時間短い優先'));
      await tester.pump();

      expect(selectedValue, 'shortTime');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('route transport control exposes three independent choices', (
    tester,
  ) async {
    String? changedTransport;
    bool? changedValue;

    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Center(
          child: SizedBox(
            width: 320,
            child: RouteTransportControl(
              selected: TransportServiceId.legacyDefault,
              onChanged: (transport, enabled) {
                changedTransport = transport;
                changedValue = enabled;
              },
            ),
          ),
        ),
      ),
    );

    expect(find.text('都営バス'), findsOneWidget);
    expect(find.text('都営地下鉄'), findsOneWidget);
    expect(find.text('東京メトロ'), findsOneWidget);
    expect(find.text('無料で利用できる交通機関を選択'), findsOneWidget);

    await tester.tap(find.text('東京メトロ'));
    await tester.pump();

    expect(changedTransport, TransportServiceId.tokyoMetro);
    expect(changedValue, isTrue);
    expect(tester.takeException(), isNull);
  });

  for (final entry in <Locale, List<String>>{
    const Locale('en'): [
      'Select transport you can use free of charge',
      'Toei Bus',
      'Toei Subway',
      'Tokyo Metro',
    ],
    const Locale('zh'): ['选择可免费乘坐的交通工具', '都营巴士', '都营地铁', '东京地铁'],
    const Locale('zh', 'TW'): ['選擇可免費搭乘的交通工具', '都營巴士', '都營地下鐵', '東京地鐵'],
    const Locale('ko'): ['무료로 이용할 수 있는 교통수단 선택', '도에이 버스', '도에이 지하철', '도쿄 메트로'],
  }.entries) {
    testWidgets('transport choices are localized for ${entry.key}', (
      tester,
    ) async {
      await tester.pumpWidget(
        CupertinoApp(
          locale: entry.key,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Center(
            child: SizedBox(
              width: 320,
              child: RouteTransportControl(
                selected: TransportServiceId.legacyDefault,
                onChanged: (_, _) {},
              ),
            ),
          ),
        ),
      );

      for (final label in entry.value) {
        expect(find.text(label), findsOneWidget);
      }
      expect(tester.takeException(), isNull);
    });
  }
}
