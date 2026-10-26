import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/pages/fare_policy_settings_page.dart';
import 'package:toeigo/providers/city_profile_provider.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('Tokyo settings do not offer ticket or fare policy selection', (
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

    expect(
      find.text('Select transport you can use free of charge'),
      findsOneWidget,
    );
    expect(
      find.text(
        'On the search screen, select the transport services you can use free '
        'of charge. The app does not determine or guarantee your eligibility.',
      ),
      findsOneWidget,
    );
    expect(find.text('Regular fare'), findsNothing);
    expect(
      find.text('Toei Transportation Pass for People with Mental Disabilities'),
      findsNothing,
    );
    expect(find.text('Free pass'), findsNothing);
    expect(find.text('View official information'), findsNothing);
    await tester.scrollUntilVisible(find.text('Open other settings'), 200);
    expect(find.text('Open other settings'), findsOneWidget);
  });
}
