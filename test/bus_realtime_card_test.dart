import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/route_models.dart';
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

  Candidate candidateWithSteps(List<StepSeg> steps) => Candidate(
    id: 'active-route-test',
    lines: const [],
    rides: steps.where((step) => step.isRide).length,
    boards: steps.where((step) => step.isRide).length,
    transfers: 0,
    total: 0,
    totalTime: 0,
    steps: steps,
    points: const [],
  );

  test('no bus route has no trackable bus', () {
    final candidate = candidateWithSteps([
      StepSeg(stepId: 'walk-1', kind: 'walk', title: '徒歩'),
    ]);

    expect(resolveTrackableBusStep(candidate), isNull);
  });

  test('valid bus route resolves the first bus', () {
    final first = StepSeg(
      stepId: 'bus-1',
      kind: 'bus',
      title: '都01',
      routeId: '006',
      tripId: '08501-1-09-170-2018',
    );
    final second = StepSeg(
      stepId: 'bus-2',
      kind: 'bus',
      title: '都02',
      routeId: '002',
      tripId: '08502-1-09-170-2020',
    );
    final candidate = candidateWithSteps([first, second]);

    expect(resolveTrackableBusStep(candidate), same(first));
  });

  for (final missingField in ['routeId', 'tripId']) {
    test('bus route fails fast when $missingField is missing', () {
      final candidate = candidateWithSteps([
        StepSeg(
          stepId: 'bus-invalid',
          kind: 'bus',
          title: '都01',
          routeId: missingField == 'routeId' ? null : '006',
          tripId: missingField == 'tripId'
              ? null
              : '08501-1-09-170-2018',
        ),
      ]);

      expect(
        () => resolveTrackableBusStep(candidate),
        throwsA(
          isA<StateError>().having(
            (error) => error.message,
            'message',
            contains('追跡対象bus stepに$missingFieldがありません'),
          ),
        ),
      );
    });
  }

  test('later invalid bus is not hidden behind an earlier valid bus', () {
    final candidate = candidateWithSteps([
      StepSeg(
        stepId: 'bus-valid',
        kind: 'bus',
        title: '都01',
        routeId: '006',
        tripId: '08501-1-09-170-2018',
      ),
      StepSeg(
        stepId: 'bus-invalid-later',
        kind: 'bus',
        title: '都02',
        routeId: '002',
      ),
    ]);

    expect(
      () => resolveTrackableBusStep(candidate),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          contains('stepId=bus-invalid-later'),
        ),
      ),
    );
  });

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
