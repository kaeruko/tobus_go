import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/pages/home_page.dart';

void main() {
  testWidgets(
    'defers the segmented control until a positive width is available',
    (tester) async {
      var width = 0.0;
      String? selectedValue;
      late StateSetter setTestState;

      await tester.pumpWidget(
        CupertinoApp(
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
}
