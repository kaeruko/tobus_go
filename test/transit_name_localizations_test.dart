import 'package:flutter/widgets.dart';
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
    const stop = StopPoint(
      name: '蔵前',
      nameEn: 'Kuramae',
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
}
