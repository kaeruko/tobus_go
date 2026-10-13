import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/pages/fare_policy_settings_page.dart';
import 'package:toeigo/providers/city_profile_provider.dart';
import 'package:toeigo/services/fare_policy_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('Tokyo fare settings render English policy names', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [cityProfileProvider.overrideWithValue(tokyoCityProfile)],
        child: CupertinoApp(
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: const FarePolicySettingsPage(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Fares & passes'), findsOneWidget);
    expect(find.text('Regular fare'), findsWidgets);
    expect(
      find.text('Toei Transportation Pass for People with Mental Disabilities'),
      findsOneWidget,
    );
    expect(find.text('Free pass'), findsOneWidget);
    expect(find.text('View official information'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Open other settings'), 200);
    expect(find.text('Open other settings'), findsOneWidget);
  });

  testWidgets('Yokohama welfare pass can be selected in English', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [cityProfileProvider.overrideWithValue(yokohamaCityProfile)],
        child: CupertinoApp(
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: const FarePolicySettingsPage(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final pass = find.text('Yokohama Welfare Special Transit Pass');
    expect(pass, findsOneWidget);
    expect(find.textContaining('A disability certificate alone'), findsOneWidget);
    await tester.scrollUntilVisible(pass, 100);
    await tester.tap(pass);
    await tester.pumpAndSettle();
    expect(await FarePolicyPreferences.load(yokohamaCityProfile),
        'yokohama_welfare_special_pass');
  });
}
