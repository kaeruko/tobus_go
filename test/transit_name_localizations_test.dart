import 'package:flutter/widgets.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/l10n/transit_name_localizations.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  test('English ride title requires explicit official English text', () {
    final step = StepSeg(
      stepId: 'bus-1',
      kind: 'bus',
      title: '上23 上野松坂屋前行',
      fromName: '平井七丁目',
      toName: '上野松坂屋前',
    );

    expect(
      () => localizedRideTitle(const Locale('en'), step),
      throwsStateError,
    );
  });

  test('English ride title uses explicit official English text', () {
    final step = StepSeg(
      stepId: 'bus-1',
      kind: 'bus',
      title: '上23 上野松坂屋前行',
      titleEn: '上23 · Ueno-matsuzakaya-mae',
      fromName: '平井七丁目',
      fromNameEn: 'Hirai-nanachome',
      toName: '上野松坂屋前',
      toNameEn: 'Ueno-matsuzakaya-mae',
    );

    expect(
      localizedRideTitle(const Locale('en'), step),
      '上23 · Ueno-matsuzakaya-mae',
    );
    expect(
      localizedRideFromName(const Locale('en'), step),
      'Hirai-nanachome (平井七丁目)',
    );
    expect(
      localizedRideToName(const Locale('en'), step),
      'Ueno-matsuzakaya-mae (上野松坂屋前)',
    );
  });

  test('English stop names keep Japanese text for matching signage', () {
    final stop = StopPoint(
      name: '蔵前',
      nameEn: 'Kuramae',
      point: const LatLng(35.703, 139.790),
      stopId: 'odpt.Station:Toei.Asakusa.Kuramae',
    );

    expect(
      localizedStopName(const Locale('en'), stop),
      'Kuramae (蔵前)',
    );
    expect(
      localizedStopName(const Locale('ja'), stop),
      '蔵前',
    );
  });

  test('identical English and Japanese transit names are not duplicated', () {
    expect(
      localizedTransitName(
        const Locale('en'),
        japanese: 'A1',
        english: 'A1',
        field: 'name_en',
        identity: 'test',
      ),
      'A1',
    );
  });

  test('official English stop names fail fast for null, empty, and blank', () {
    for (final english in <String?>[null, '', '   ']) {
      final stop = StopPoint(
        name: '蔵前',
        nameEn: english,
        point: const LatLng(35.703, 139.790),
        stopId: 'stop-kuramae',
      );

      expect(
        () => localizedStopName(const Locale('en'), stop),
        throwsA(
          isA<StateError>().having(
            (error) => error.message.toString(),
            'diagnostic',
            allOf(contains('field=name_en'), contains('stopId=stop-kuramae')),
          ),
        ),
      );
    }
  });

  test('generic walk place may omit English but rejects blank English', () {
    expect(
      localizedOptionalPlaceName(
        const Locale('en'),
        japanese: '横浜赤レンガ倉庫入口',
        english: null,
        field: 'walk_to_en',
        identity: 'stepId=walk-1',
      ),
      '横浜赤レンガ倉庫入口',
    );

    expect(
      () => localizedOptionalPlaceName(
        const Locale('en'),
        japanese: '横浜赤レンガ倉庫入口',
        english: '   ',
        field: 'walk_to_en',
        identity: 'stepId=walk-1',
      ),
      throwsA(
        isA<StateError>().having(
          (error) => error.message.toString(),
          'diagnostic',
          allOf(contains('field=walk_to_en'), contains('stepId=walk-1')),
        ),
      ),
    );
  });

}
