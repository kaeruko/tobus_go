import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/pages/force_update_page.dart';

void main() {
  testWidgets('force update page uses Japanese remote message', (tester) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: const ForceUpdatePage(
          messageJa: '重要な更新があります。最新版へ更新してください。',
          messageEn: 'A required update is available.',
          currentVersion: '1.0.0',
          minimumVersion: '1.0.1',
          storeUri: null,
        ),
      ),
    );

    expect(find.text('アップデートが必要です'), findsOneWidget);
    expect(
      find.text('重要な更新があります。最新版へ更新してください。'),
      findsOneWidget,
    );
    expect(find.text('現在のバージョン: 1.0.0'), findsOneWidget);
    expect(find.text('必要なバージョン: 1.0.1 以降'), findsOneWidget);
    expect(find.text('最新版に更新'), findsNothing);
  });

  testWidgets('force update page uses English remote message', (tester) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: ForceUpdatePage(
          messageJa: '更新',
          messageEn: 'A required update is available.',
          currentVersion: '1.0.0',
          minimumVersion: '1.0.1',
          storeUri: Uri.parse(
            'https://play.google.com/store/apps/details?id=jp.cloxs.toeigo',
          ),
        ),
      ),
    );

    expect(find.text('Update required'), findsOneWidget);
    expect(find.text('A required update is available.'), findsOneWidget);
    expect(find.text('Current version: 1.0.0'), findsOneWidget);
    expect(find.text('Required version: 1.0.1 or later'), findsOneWidget);
    expect(find.text('Update now'), findsOneWidget);
  });
}
