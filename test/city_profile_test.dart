import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/services/bus_location_source.dart';

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

    test('nagoya is route-search-only and has isolated distribution IDs', () {
      final profile = cityProfileForKey('nagoya');

      expect(profile.appName, '名古屋でGO');
      expect(profile.capabilities.features.routeSearchOnly, isTrue);
      expect(profile.capabilities.features.outingDiscovery, isFalse);
      expect(profile.capabilities.features.savedRoutes, isFalse);
      expect(profile.capabilities.features.history, isFalse);
      expect(profile.capabilities.features.groupTrips, isFalse);
      expect(profile.capabilities.realtime.vehiclePosition, isFalse);
      expect(profile.capabilities.realtime.tripUpdates, isFalse);
      expect(profile.capabilities.realtime.alerts, isFalse);
      expect(
        profile.farePolicies.map((option) => option.id),
        ['normal', 'nagoya_welfare_special_pass'],
      );
      expect(profile.distribution.androidApplicationId, 'jp.cloxs.nagoyago');
      expect(profile.distribution.iosBundleIdentifier, 'jp.cloxs.nagoyago');
      expect(profile.distribution.firebaseEnabled, isFalse);
    });

    test('fare policy IDs are city scoped and exact', () {
      expect(
        nagoyaCityProfile.farePolicyById('nagoya_welfare_special_pass').id,
        'nagoya_welfare_special_pass',
      );
      expect(
        () => nagoyaCityProfile.farePolicyById('tokyo_toei_transport_pass'),
        throwsStateError,
      );
      expect(
        () => nagoyaCityProfile.farePolicyById(' normal'),
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
      expect(profile.farePolicies.map((option) => option.id), ['normal']);
      expect(profile.distribution.androidApplicationId, 'jp.cloxs.go.sendai');
      expect(profile.distribution.iosBundleIdentifier, 'jp.cloxs.go.sendai');
      expect(profile.distribution.firebaseEnabled, isFalse);
    });

    test('yokohama exposes bus vehicle realtime only', () {
      final profile = cityProfileForKey('yokohama');

      expect(profile.appName, '横浜でGO');
      expect(profile.capabilities.features.routeSearchOnly, isTrue);
      expect(profile.capabilities.features.outingDiscovery, isFalse);
      expect(profile.capabilities.features.savedRoutes, isFalse);
      expect(profile.capabilities.features.history, isFalse);
      expect(profile.capabilities.features.groupTrips, isFalse);
      expect(profile.capabilities.realtime.vehiclePosition, isTrue);
      expect(profile.capabilities.realtime.tripUpdates, isFalse);
      expect(profile.capabilities.realtime.alerts, isFalse);
      expect(profile.farePolicies.map((option) => option.id), ['normal']);
      expect(profile.distribution.androidApplicationId, 'jp.cloxs.go.yokohama');
      expect(profile.distribution.iosBundleIdentifier, 'jp.cloxs.go.yokohama');
      expect(profile.distribution.firebaseEnabled, isFalse);
    });

    test('APP_CITY values are exact and unsupported values fail fast', () {
      expect(() => cityProfileForKey('Tokyo'), throwsStateError);
      expect(() => cityProfileForKey(' nagoya'), throwsStateError);
      expect(() => cityProfileForKey('sapporo'), throwsStateError);
    });

    test('native flavor selects the same city without APP_CITY', () {
      expect(resolveConfiguredCityKey(flavor: 'tokyo', dartDefine: ''), 'tokyo');
      expect(
        resolveConfiguredCityKey(flavor: 'nagoya', dartDefine: ''),
        'nagoya',
      );
      expect(
        resolveConfiguredCityKey(flavor: 'sendai', dartDefine: ''),
        'sendai',
      );
      expect(
        resolveConfiguredCityKey(flavor: 'yokohama', dartDefine: ''),
        'yokohama',
      );
    });

    test('flavor and APP_CITY mismatch fails instead of choosing one', () {
      expect(
        () => resolveConfiguredCityKey(
          flavor: 'nagoya',
          dartDefine: 'tokyo',
        ),
        throwsStateError,
      );
      expect(
        () => resolveConfiguredCityKey(
          flavor: 'yokohama',
          dartDefine: 'tokyo',
        ),
        throwsStateError,
      );
    });

    test('flavor and APP_CITY values are not whitespace-normalized', () {
      expect(
        () => resolveConfiguredCityKey(flavor: ' nagoya', dartDefine: ''),
        throwsStateError,
      );
      expect(
        () => resolveConfiguredCityKey(flavor: null, dartDefine: 'nagoya '),
        throwsStateError,
      );
    });

    test('unflavored tests and legacy local development remain Tokyo', () {
      expect(resolveConfiguredCityKey(flavor: null, dartDefine: ''), 'tokyo');
    });
  });

  test('realtime bus source refuses a city without VehiclePosition', () async {
    const source = RealtimeBusLocationSource(cityProfile: nagoyaCityProfile);

    await expectLater(
      source.fetch(routeId: 'route', tripId: 'trip'),
      throwsA(
        isA<BusLocationNotAvailableException>().having(
          (error) => error.code,
          'code',
          'realtime_vehicle_position_unsupported:nagoya',
        ),
      ),
    );
  });
}
