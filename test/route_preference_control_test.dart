import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart' show Tooltip;
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

  testWidgets('transport choices use a single row of icons with independent toggles', (
    tester,
  ) async {
    final changes = <(String, bool)>[];

    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Center(
          child: SizedBox(
            width: 240,
            child: RouteTransportControl(
              selected: TransportServiceId.legacyDefault,
              onChanged: (transport, enabled) {
                changes.add((transport, enabled));
              },
            ),
          ),
        ),
      ),
    );

    expect(find.text('無料で利用できる交通機関を選択'), findsOneWidget);
    expect(find.text('🚌'), findsOneWidget);
    expect(find.text('🚇'), findsOneWidget);
    expect(find.text('都営バス'), findsNothing);
    expect(find.text('都営地下鉄'), findsNothing);
    expect(find.text('東京メトロ'), findsNothing);

    final metroLogo = tester.widget<Image>(
      find.byWidgetPredicate(
        (widget) =>
            widget is Image &&
            widget.image is AssetImage &&
            (widget.image as AssetImage).assetName ==
                'assets/images/tokyo_metro_mark.png',
      ),
    );
    expect(metroLogo.width, 30);
    expect(metroLogo.height, 30);

    final bus = find.byKey(const Key('transport-toei-bus'));
    final subway = find.byKey(const Key('transport-toei-subway'));
    final metro = find.byKey(const Key('transport-tokyo-metro'));
    expect(tester.getCenter(bus).dy, tester.getCenter(subway).dy);
    expect(tester.getCenter(bus).dy, tester.getCenter(metro).dy);
    for (final choice in [bus, subway, metro]) {
      expect(tester.getSize(choice).height, greaterThanOrEqualTo(48));
    }

    await tester.tap(bus);
    await tester.tap(subway);
    await tester.tap(metro);
    await tester.pump();
    expect(changes, [
      (TransportServiceId.toeiBus, false),
      (TransportServiceId.toeiSubway, false),
      (TransportServiceId.tokyoMetro, true),
    ]);

    await tester.longPress(metro);
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('東京メトロ'), findsOneWidget);
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

      expect(find.text(entry.value.first), findsOneWidget);
      final tooltipMessages = tester
          .widgetList<Tooltip>(find.byType(Tooltip))
          .map((tooltip) => tooltip.message)
          .toList();
      expect(tooltipMessages, entry.value.skip(1).toList());
      for (final label in entry.value.skip(1)) {
        expect(find.text(label), findsNothing);
      }
      expect(tester.takeException(), isNull);
    });
  }
}
