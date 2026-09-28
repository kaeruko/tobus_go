import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/widgets/app_navigation_bar.dart';

void main() {
  testWidgets('Tokyo brand header uses the Japanese logo in Japanese', (
    tester,
  ) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: CupertinoPageScaffold(
          navigationBar: buildAppNavigationBar(
            middle: cityBrandNavigationTitle(
              city: AppCity.tokyo,
              fallbackTitle: '都営でGO',
            ),
          ),
          child: const SizedBox.shrink(),
        ),
      ),
    );

    final image = tester.widget<Image>(find.byType(Image));
    final provider = image.image;
    expect(provider, isA<AssetImage>());
    expect((provider as AssetImage).assetName, 'assets/icon/tokyo.png');
    expect(image.height, 34);
  });

  testWidgets('Tokyo brand header uses the English logo in English', (
    tester,
  ) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: CupertinoPageScaffold(
          navigationBar: buildAppNavigationBar(
            middle: cityBrandNavigationTitle(
              city: AppCity.tokyo,
              fallbackTitle: 'Toei GO',
            ),
          ),
          child: const SizedBox.shrink(),
        ),
      ),
    );

    final image = tester.widget<Image>(find.byType(Image));
    final provider = image.image;
    expect(provider, isA<AssetImage>());
    expect((provider as AssetImage).assetName, 'assets/icon/tokyo_en.png');
    expect(image.height, 34);
  });

  testWidgets('cities without a logo asset keep their localized title', (
    tester,
  ) async {
    await tester.pumpWidget(
      CupertinoApp(
        home: CupertinoPageScaffold(
          navigationBar: buildAppNavigationBar(
            middle: cityBrandNavigationTitle(
              city: AppCity.nagoya,
              fallbackTitle: '名古屋でGO',
            ),
          ),
          child: const SizedBox.shrink(),
        ),
      ),
    );

    expect(find.text('名古屋でGO'), findsOneWidget);
    expect(find.byType(Image), findsNothing);
  });
}
