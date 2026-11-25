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
