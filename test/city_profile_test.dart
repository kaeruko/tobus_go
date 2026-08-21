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
    });

    test('nagoya is route-search-only and has no realtime capability', () {
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
    });

    test('sendai exposes all planned GTFS-Realtime capabilities', () {
      final profile = cityProfileForKey('sendai');

      expect(profile.appName, '仙台でGO');
      expect(profile.capabilities.features.routeSearchOnly, isTrue);
      expect(profile.capabilities.features.outingDiscovery, isFalse);
      expect(profile.capabilities.features.groupTrips, isFalse);
      expect(profile.capabilities.realtime.vehiclePosition, isTrue);
      expect(profile.capabilities.realtime.tripUpdates, isTrue);
      expect(profile.capabilities.realtime.alerts, isTrue);
    });

    test('APP_CITY values are exact and unsupported values fail fast', () {
      expect(() => cityProfileForKey('Tokyo'), throwsStateError);
      expect(() => cityProfileForKey(' nagoya'), throwsStateError);
      expect(() => cityProfileForKey('sapporo'), throwsStateError);
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
