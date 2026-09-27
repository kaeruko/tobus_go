import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/services/bus_location_source.dart';
import 'package:toeigo/widgets/active_route_content.dart';

void main() {
  late AppLocalizations ja;
  late AppLocalizations en;

  setUpAll(() async {
    ja = await AppLocalizations.delegate.load(const Locale('ja'));
    en = await AppLocalizations.delegate.load(const Locale('en'));
  });

  BusLocation location({
    required String status,
    bool beforeFirstStop = false,
    String? rawStopNameEn = 'Yokohama Station',
  }) => BusLocation(
    vehicleId: '3438',
    fromStopId: beforeFirstStop ? null : 'stop-1',
    routeId: 'yokohama_bus:008',
    tripId: 'yokohama_bus:T1',
    vehicleLat: 35.465,
    vehicleLon: 139.625,
    beforeFirstStop: beforeFirstStop,
    rawStopId: 'stop-1',
    rawStopName: '横浜駅前',
    rawStopNameEn: rawStopNameEn,
    currentStatus: status,
  );

  test('IN_TRANSIT_TO says the bus is heading to the stop', () {
    expect(
      busRealtimeStatusText(location(status: 'IN_TRANSIT_TO'), l10n: ja, locale: const Locale('ja')),
      '横浜駅前へ向かっています',
    );
  });

  test('STOPPED_AT says the bus is stopped at the stop', () {
    expect(
      busRealtimeStatusText(location(status: 'STOPPED_AT'), l10n: ja, locale: const Locale('ja')),
      '横浜駅前に停車中',
    );
  });

  test('before-first-stop takes precedence over vehicle status', () {
    expect(
      busRealtimeStatusText(
        location(status: 'IN_TRANSIT_TO', beforeFirstStop: true),
        l10n: ja,
        locale: const Locale('ja'),
      ),
      '横浜駅前（始発停留所）へ向かっています',
    );
  });

  test('unknown realtime status fails fast', () {
    expect(
      () => busRealtimeStatusText(location(status: 'UNKNOWN'), l10n: ja, locale: const Locale('ja')),
      throwsStateError,
    );
  });
  test('English realtime stop requires official English diagnostics', () {
    for (final english in <String?>[null, '', '   ']) {
      expect(
        () => busRealtimeStatusText(
          location(status: 'IN_TRANSIT_TO', rawStopNameEn: english),
          l10n: en,
          locale: const Locale('en'),
        ),
        throwsA(
          isA<StateError>().having(
            (error) => error.message.toString(),
            'diagnostic',
            allOf(
              contains('field=raw_stop_name_en'),
              contains('stopId=stop-1'),
            ),
          ),
        ),
      );
    }
  });

  test('English realtime status uses the same vehicle state', () {
    expect(
      busRealtimeStatusText(location(status: 'IN_TRANSIT_TO'), l10n: en, locale: const Locale('en')),
      'Heading to Yokohama Station (横浜駅前)',
    );
    expect(
      busRealtimeStatusText(location(status: 'STOPPED_AT'), l10n: en, locale: const Locale('en')),
      'Stopped at Yokohama Station (横浜駅前)',
    );
    expect(
      busRealtimeStatusText(
        location(status: 'IN_TRANSIT_TO', beforeFirstStop: true),
        l10n: en,
        locale: const Locale('en'),
      ),
      'Heading to Yokohama Station (横浜駅前) (first stop)',
    );
  });

}
