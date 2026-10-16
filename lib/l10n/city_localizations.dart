import '../core/city_profile.dart';
import 'app_localizations.dart';

String localizedCityAppName(AppLocalizations l10n, AppCity city) {
  switch (city) {
    case AppCity.tokyo:
      return l10n.appNameTokyo;
    case AppCity.sendai:
      return l10n.appNameSendai;
  }
}
