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
      'Hirai-nanachome',
    );
    expect(
      localizedRideToName(const Locale('en'), step),
      'Ueno-matsuzakaya-mae',
    );
  });
}
