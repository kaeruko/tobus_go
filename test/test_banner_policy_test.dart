import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/core/test_banner_policy.dart';

void main() {
  String? unit({
    bool debug = true,
    bool requested = true,
    bool web = false,
    TargetPlatform platform = TargetPlatform.android,
    String city = 'tokyo',
  }) => testBannerUnitId(
    debug: debug,
    requested: requested,
    web: web,
    platform: platform,
    cityKey: city,
  );

  test('only explicitly opted-in Tokyo mobile debug builds use sample units', () {
    expect(unit(), 'ca-app-pub-3940256099942544/6300978111');
    expect(unit(platform: TargetPlatform.iOS),
        'ca-app-pub-3940256099942544/2934735716');
    expect(unit(debug: false), isNull);
    expect(unit(requested: false), isNull);
    expect(unit(web: true), isNull);
    expect(unit(city: 'sendai'), isNull);
    expect(unit(platform: TargetPlatform.windows), isNull);
    expect(unit(platform: TargetPlatform.macOS), isNull);
    expect(unit(platform: TargetPlatform.linux), isNull);
    expect(unit(platform: TargetPlatform.fuchsia), isNull);
  });
}
