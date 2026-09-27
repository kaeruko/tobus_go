import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/explore_models.dart';

void main() {
  test('Explore editorial content keeps Japanese and English separately', () {
    final content = ExploreEditorialContent.fromJson({
      'spots': [
        {
          'stop_id': 'odpt.BusstopPole:Toei.OshiageStation.100.1',
          'comment': 'スカイツリーが近い',
          'comment_en': 'Tokyo Skytree is nearby',
          'images': [
            {
              'file': 'oshiage.jpg',
              'caption': '駅前から見たスカイツリー',
              'caption_en': 'Tokyo Skytree from the bus stop',
            },
          ],
        },
      ],
    });

    final spot =
        content.byStopId['odpt.BusstopPole:Toei.OshiageStation.100.1']!;
    expect(spot.commentForLanguageCode('ja'), 'スカイツリーが近い');
    expect(spot.commentForLanguageCode('en'), 'Tokyo Skytree is nearby');
    expect(
      spot.images.single.captionForLanguageCode('ja'),
      '駅前から見たスカイツリー',
    );
    expect(
      spot.images.single.captionForLanguageCode('en'),
      'Tokyo Skytree from the bus stop',
    );
  });

  test('missing English editorial copy stays empty instead of falling back', () {
    final content = ExploreEditorialContent.fromJson({
      'spots': [
        {
          'stop_id': 'odpt.BusstopPole:Toei.OshiageStation.100.1',
          'comment': '日本語だけ',
          'comment_en': '',
          'images': [
            {
              'file': 'oshiage.jpg',
              'caption': '日本語キャプション',
              'caption_en': '',
            },
          ],
        },
      ],
    });

    final spot =
        content.byStopId['odpt.BusstopPole:Toei.OshiageStation.100.1']!;
    expect(spot.commentForLanguageCode('en'), isEmpty);
    expect(spot.images.single.captionForLanguageCode('en'), isEmpty);
  });

  test('Explore stop names use official English names without fallback', () {
    final response = ReachableResponse.fromJson({
      'found': true,
      'nearest_stop': {
        'id': 'origin',
        'name': '押上駅前',
        'name_en': 'Oshiage Sta.',
        'lat': 35.0,
        'lon': 139.0,
        'dist_m': 120,
      },
      'reachable_stops': [
        {
          'id': 'destination',
          'name': '業平橋',
          'name_en': 'Narihira-bashi',
          'lat': 35.1,
          'lon': 139.1,
          'via_route': 'odpt.Busroute:Toei.Ue23',
        },
      ],
    });

    expect(response.nearestStop!.nameForLanguageCode('ja'), '押上駅前');
    expect(response.nearestStop!.nameForLanguageCode('en'), 'Oshiage Sta.');
    expect(
      response.reachableStops.single.nameForLanguageCode('en'),
      'Narihira-bashi',
    );
  });

  test('Explore stop parsing fails fast when official English name is missing',
      () {
    expect(
      () => ReachableResponse.fromJson({
        'found': true,
        'nearest_stop': {
          'id': 'origin',
          'name': '押上駅前',
          'lat': 35.0,
          'lon': 139.0,
          'dist_m': 120,
        },
        'reachable_stops': const [],
      }),
      throwsA(isA<FormatException>()),
    );
  });

  test('bilingual schema fails fast when English fields are missing', () {
    expect(
      () => ExploreEditorialContent.fromJson({
        'spots': [
          {
            'stop_id': 'odpt.BusstopPole:Toei.OshiageStation.100.1',
            'comment': '日本語だけ',
            'images': const [],
          },
        ],
      }),
      throwsA(isA<FormatException>()),
    );
  });
}
