import 'package:flutter/foundation.dart';

const _testAdsRequested = bool.fromEnvironment('TOEIGO_TEST_ADS');

/// Google sample banner units only; never substitute a real ad unit here.
String? testBannerUnitId({
  required bool debug,
  required bool requested,
  required bool web,
  required TargetPlatform platform,
  required String cityKey,
}) {
  if (!debug || !requested || web || cityKey != 'tokyo') return null;
  switch (platform) {
    case TargetPlatform.android:
      return 'ca-app-pub-3940256099942544/6300978111';
    case TargetPlatform.iOS:
      return 'ca-app-pub-3940256099942544/2934735716';
    default:
      return null;
  }
}

String? configuredTestBannerUnitId(String cityKey) => testBannerUnitId(
  debug: kDebugMode,
  requested: _testAdsRequested,
  web: kIsWeb,
  platform: defaultTargetPlatform,
  cityKey: cityKey,
);

const _testUmpRequested = bool.fromEnvironment('TOEIGO_TEST_UMP');

bool configuredConsentTestEnabled(String cityKey) =>
    _testUmpRequested && configuredTestBannerUnitId(cityKey) != null;

const _productionAdsRequested = bool.fromEnvironment('TOEIGO_PRODUCTION_ADS');

/// No profile-build ads, no debug production ads and no non-Tokyo ads.
/// Production requires an explicit release build define and UMP permission.
String? productionBannerUnitId({
  required bool release,
  required bool requested,
  required bool web,
  required TargetPlatform platform,
  required String cityKey,
}) {
  if (!release || !requested || web || cityKey != 'tokyo') return null;
  switch (platform) {
    case TargetPlatform.android:
      return 'ca-app-pub-1701253412237513/5953725636';
    case TargetPlatform.iOS:
      return 'ca-app-pub-1701253412237513/2050652992';
    default:
      return null;
  }
}

String? configuredProductionBannerUnitId(String cityKey) =>
    productionBannerUnitId(
      release: kReleaseMode,
      requested: _productionAdsRequested,
      web: kIsWeb,
      platform: defaultTargetPlatform,
      cityKey: cityKey,
    );

String? configuredBannerUnitId(String cityKey) => kReleaseMode
    ? configuredProductionBannerUnitId(cityKey)
    : configuredTestBannerUnitId(cityKey);

bool configuredAdConsentRequired(String cityKey) => kReleaseMode
    ? configuredProductionBannerUnitId(cityKey) != null
    : configuredConsentTestEnabled(cityKey);
