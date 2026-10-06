import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/l10n/city_localizations.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'Simplified Chinese resources expose localized search and settings',
    () async {
      final l10n = await AppLocalizations.delegate.load(const Locale('zh'));

      expect(localizedCityAppName(l10n, AppCity.tokyo), '都营GO');
      expect(l10n.tabSearch, '搜索');
      expect(l10n.departureSearch, '出发地');
      expect(l10n.arrivalSearch, '目的地');
      expect(l10n.languageSettingsTitle, '语言');
      expect(l10n.transportBusOnly, '仅都营巴士');
    },
  );

  test(
    'Traditional Chinese Taiwan resources expose localized search and settings',
    () async {
      final locale = Locale.fromSubtags(
        languageCode: 'zh',
        scriptCode: 'Hant',
        countryCode: 'TW',
      );
      final l10n = await AppLocalizations.delegate.load(locale);

      expect(localizedCityAppName(l10n, AppCity.tokyo), '都營GO');
      expect(l10n.tabSearch, '搜尋');
      expect(l10n.departureSearch, '出發地');
      expect(l10n.arrivalSearch, '目的地');
      expect(l10n.languageSettingsTitle, '語言');
      expect(l10n.transportBusOnly, '僅限都營巴士');
      expect(AppLocalizations.supportedLocales, contains(locale));
    },
  );

  test('English resources expose localized city and search labels', () async {
    final l10n = await AppLocalizations.delegate.load(const Locale('en'));

    expect(localizedCityAppName(l10n, AppCity.tokyo), 'Toei GO');
    expect(localizedCityAppName(l10n, AppCity.nagoya), 'Nagoya GO');
    expect(l10n.tabSearch, 'Search');
    expect(l10n.departureSearch, 'From');
    expect(l10n.arrivalSearch, 'To');
    expect(l10n.transportBusOnly, 'Toei bus only');
  });

  test('Japanese resources preserve the existing labels', () async {
    final l10n = await AppLocalizations.delegate.load(const Locale('ja'));

    expect(localizedCityAppName(l10n, AppCity.tokyo), '都営でGO');
    expect(l10n.tabSearch, '検索');
    expect(l10n.departureSearch, '出発(検索)');
    expect(l10n.arrivalSearch, '到着(検索)');
    expect(l10n.transportBusOnly, '都営バスのみ');
  });
}
