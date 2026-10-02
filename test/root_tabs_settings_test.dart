import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/pages/root_tabs.dart';
import 'package:toeigo/providers/active_trip_provider.dart';

class _FakeActiveTripNotifier extends StateNotifier<AsyncValue<Trip?>> {
  _FakeActiveTripNotifier() : super(const AsyncValue.data(null));
}

void main() {
  testWidgets('root tabs expose settings in the bottom navigation', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          activeTripProvider.overrideWith(
            (ref) => _FakeActiveTripNotifier(),
          ),
        ],
        child: const MaterialApp(
          locale: Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: RootTabs(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('設定'), findsOneWidget);
    expect(find.byIcon(CupertinoIcons.settings), findsOneWidget);
  });
}
