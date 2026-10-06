import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';

void main() {
  test('system locales resolve to the supported app catalogs', () {
    final cases = <(Locale, Locale)>[
      (const Locale('ja', 'JP'), const Locale('ja')),
      (const Locale('en', 'US'), const Locale('en')),
      (const Locale('zh', 'CN'), const Locale('zh')),
      (
        const Locale.fromSubtags(languageCode: 'zh', scriptCode: 'Hans'),
        const Locale('zh'),
      ),
      (
        const Locale('zh', 'TW'),
        const Locale.fromSubtags(
          languageCode: 'zh',
          scriptCode: 'Hant',
          countryCode: 'TW',
        ),
      ),
      (
        const Locale.fromSubtags(languageCode: 'zh', scriptCode: 'Hant'),
        const Locale.fromSubtags(
          languageCode: 'zh',
          scriptCode: 'Hant',
          countryCode: 'TW',
        ),
      ),
      (
        const Locale.fromSubtags(
          languageCode: 'zh',
          scriptCode: 'Hant',
          countryCode: 'TW',
        ),
        const Locale.fromSubtags(
          languageCode: 'zh',
          scriptCode: 'Hant',
          countryCode: 'TW',
        ),
      ),
    ];

    for (final (deviceLocale, expectedLocale) in cases) {
      expect(
        basicLocaleListResolution(
          [deviceLocale],
          AppLocalizations.supportedLocales,
        ),
        expectedLocale,
      );
    }
  });
}
