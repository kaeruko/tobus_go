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
