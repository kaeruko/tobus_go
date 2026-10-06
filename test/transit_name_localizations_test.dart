import 'package:flutter/widgets.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/l10n/transit_name_localizations.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  test('Japanese ride title hides parenthesized ODPT route alias', () {
    final step = StepSeg(
      stepId: 'bus-to01',
      kind: 'bus',
      title: '都01（T01） 渋谷駅前行',
      fromName: '新橋駅前',
      toName: '渋谷駅前',
    );

    expect(
      localizedRideTitle(const Locale('ja'), step),
      '都01 渋谷駅前行',
    );
    expect(
      normalizeJapaneseTransitDisplayText('都０１（Ｔ０１） 渋谷駅前行'),
      '都０１ 渋谷駅前行',
    );
  });

  for (final locale in [
    const Locale('en'),
    const Locale('zh', 'CN'),
    const Locale('ko', 'KR'),
  ]) {
    group('Official transit names for ${locale.toLanguageTag()}', () {
      test('English ride title requires explicit official English text', () {
        final step = StepSeg(
          stepId: 'bus-1',
          kind: 'bus',
          title: '上23 上野松坂屋前行',
          fromName: '平井七丁目',
          toName: '上野松坂屋前',
        );

        expect(() => localizedRideTitle(locale, step), throwsStateError);
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

        expect(localizedRideTitle(locale, step), '上23 · Ueno-matsuzakaya-mae');
        expect(localizedRideFromName(locale, step), 'Hirai-nanachome (平井七丁目)');
        expect(
          localizedRideToName(locale, step),
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

        expect(localizedStopName(locale, stop), 'Kuramae (蔵前)');
        expect(localizedStopName(const Locale('ja'), stop), '蔵前');
      });

      test(
        'identical English and Japanese transit names are not duplicated',
        () {
          expect(
            localizedTransitName(
              locale,
              japanese: 'A1',
              english: 'A1',
              field: 'name_en',
              identity: 'test',
            ),
            'A1',
          );
        },
      );

      test(
        'official English stop names fail fast for null, empty, and blank',
        () {
          for (final english in <String?>[null, '', '   ']) {
            final stop = StopPoint(
              name: '蔵前',
              nameEn: english,
              point: const LatLng(35.703, 139.790),
              stopId: 'stop-kuramae',
            );

            expect(
              () => localizedStopName(locale, stop),
              throwsA(
                isA<StateError>().having(
                  (error) => error.message.toString(),
                  'diagnostic',
                  allOf(
                    contains('field=name_en'),
                    contains('stopId=stop-kuramae'),
                  ),
                ),
              ),
            );
          }
        },
      );

      test('generic walk place may omit English but rejects blank English', () {
        expect(
          localizedOptionalPlaceName(
            locale,
            japanese: '横浜赤レンガ倉庫入口',
            english: null,
            field: 'walk_to_en',
            identity: 'stepId=walk-1',
          ),
          '横浜赤レンガ倉庫入口',
        );

        expect(
          () => localizedOptionalPlaceName(
            locale,
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
    });
  }
}
