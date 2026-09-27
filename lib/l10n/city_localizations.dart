import '../core/city_profile.dart';
import 'app_localizations.dart';

String localizedCityAppName(AppLocalizations l10n, AppCity city) {
  switch (city) {
    case AppCity.tokyo:
      return l10n.appNameTokyo;
    case AppCity.nagoya:
      return l10n.appNameNagoya;
    case AppCity.sendai:
      return l10n.appNameSendai;
    case AppCity.yokohama:
      return l10n.appNameYokohama;
  }
}
