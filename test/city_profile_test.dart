import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/core/city_profile.dart';

void main() {
  group('CityProfile', () {
    test('tokyo keeps existing feature and realtime capabilities', () {
      final profile = cityProfileForKey('tokyo');

      expect(profile.appName, '都営でGO');
      expect(profile.capabilities.features.routeSearchOnly, isFalse);
      expect(profile.capabilities.features.outingDiscovery, isTrue);
      expect(profile.capabilities.features.savedRoutes, isTrue);
      expect(profile.capabilities.features.history, isTrue);
      expect(profile.capabilities.features.groupTrips, isTrue);
      expect(profile.capabilities.realtime.vehiclePosition, isTrue);
      expect(profile.capabilities.realtime.tripUpdates, isFalse);
      expect(profile.capabilities.realtime.alerts, isFalse);
      expect(
        profile.farePolicies.map((option) => option.id),
        ['normal', 'tokyo_toei_transport_pass'],
      );
      expect(profile.distribution.androidApplicationId, 'jp.cloxs.toeigo');
      expect(profile.distribution.iosBundleIdentifier, 'jp.cloxs.go.tokyo');
      expect(profile.distribution.firebaseEnabled, isTrue);
    });


    test('fare policy IDs are city scoped and exact', () {
      expect(
        sendaiCityProfile.farePolicyById('normal').id,
        'normal',
      );
      expect(
        () => sendaiCityProfile.farePolicyById('tokyo_toei_transport_pass'),
        throwsStateError,
      );
      expect(
        () => sendaiCityProfile.farePolicyById(' normal'),
        throwsStateError,
      );
    });

    test('sendai exposes planned realtime and separate distribution IDs', () {
      final profile = cityProfileForKey('sendai');

      expect(profile.appName, '仙台でGO');
      expect(profile.capabilities.features.routeSearchOnly, isTrue);
      expect(profile.capabilities.features.outingDiscovery, isFalse);
      expect(profile.capabilities.features.groupTrips, isFalse);
      expect(profile.capabilities.realtime.vehiclePosition, isTrue);
      expect(profile.capabilities.realtime.tripUpdates, isTrue);
      expect(profile.capabilities.realtime.alerts, isTrue);
      expect(profile.farePolicies.map((option) => option.id),
          sendaiReviewedCoordinatesEnabled
              ? ['normal', 'sendai_fureai_pass', 'sendai_keiro_pass']
              : ['normal']);
      expect(profile.distribution.androidApplicationId, 'jp.cloxs.go.sendai');
      expect(profile.distribution.iosBundleIdentifier, 'jp.cloxs.go.sendai');
      expect(profile.distribution.firebaseEnabled, isFalse);
    });


    test('APP_CITY values are exact and unsupported values fail fast', () {
      expect(() => cityProfileForKey('Tokyo'), throwsStateError);
      expect(() => cityProfileForKey(' sendai'), throwsStateError);
      expect(() => cityProfileForKey('sapporo'), throwsStateError);
      expect(AppCity.values, [AppCity.tokyo, AppCity.sendai]);
      for (final retired in ['nagoya', 'yokohama']) {
        expect(() => cityProfileForKey(retired), throwsStateError);
        expect(() => resolveConfiguredCityKey(flavor: retired, dartDefine: ''), throwsStateError);
      }
    });

    test('native flavor selects the same city without APP_CITY', () {
      expect(resolveConfiguredCityKey(flavor: 'tokyo', dartDefine: ''), 'tokyo');
      expect(
        resolveConfiguredCityKey(flavor: 'sendai', dartDefine: ''),
        'sendai',
      );
    });

    test('flavor and APP_CITY mismatch fails instead of choosing one', () {
      expect(
        () => resolveConfiguredCityKey(
          flavor: 'sendai',
          dartDefine: 'tokyo',
        ),
        throwsStateError,
      );
    });

    test('flavor and APP_CITY values are not whitespace-normalized', () {
      expect(
        () => resolveConfiguredCityKey(flavor: ' sendai', dartDefine: ''),
        throwsStateError,
      );
      expect(
        () => resolveConfiguredCityKey(flavor: null, dartDefine: 'sendai '),
        throwsStateError,
      );
    });

    test('unflavored tests and legacy local development remain Tokyo', () {
      expect(resolveConfiguredCityKey(flavor: null, dartDefine: ''), 'tokyo');
    });
  });

}
