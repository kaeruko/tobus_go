import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/widgets/route_date_picker_panel.dart';

void main() {
  for (final brightness in Brightness.values) {
    testWidgets('date picker popup resolves its background in $brightness', (tester) async {
      await tester.pumpWidget(
        CupertinoApp(
          theme: CupertinoThemeData(brightness: brightness),
          home: CupertinoPageScaffold(
            child: Builder(
              builder: (context) => CupertinoButton(
                onPressed: () => showCupertinoModalPopup<void>(
                  context: context,
                  builder: (context) => RouteDatePickerPanel(
                    height: 250,
                    child: CupertinoDatePicker(
                      initialDateTime: DateTime(2026, 11, 25, 11),
                      use24hFormat: true,
                      onDateTimeChanged: (_) {},
                    ),
                  ),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();

      final panel = find.byType(RouteDatePickerPanel);
      final context = tester.element(panel);
      final surface = tester.widget<Container>(
        find.descendant(of: panel, matching: find.byType(Container)).first,
      );
      // Cupertino modal popups establish elevated interface level.
      // Dark systemBackground is therefore darkElevatedColor, not black.
      expect(
        CupertinoUserInterfaceLevel.of(context),
        CupertinoUserInterfaceLevelData.elevated,
      );
      final expected = brightness == Brightness.dark
          ? CupertinoColors.systemBackground.darkElevatedColor
          : CupertinoColors.systemBackground.elevatedColor;
      expect(surface.color!.toARGB32(), expected.toARGB32());
      final expectedLabel = brightness == Brightness.dark
          ? CupertinoColors.white
          : CupertinoColors.black;
      expect(
        CupertinoTheme.of(context).textTheme.dateTimePickerTextStyle.color!
            .toARGB32(),
        expectedLabel.toARGB32(),
      );
      expect(find.byType(CupertinoDatePicker), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
