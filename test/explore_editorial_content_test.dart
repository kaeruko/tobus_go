import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/explore_models.dart';

void main() {
  test('parses editorial content by stop id', () {
    final content = ExploreEditorialContent.fromJson({
      'spots': [
        {
          'stop_id': 'stop-a',
          'comment': '川沿いが気持ちいい',
          'images': [
            {
              'file': 'river.jpg',
              'caption': '川へ向かう道',
            },
          ],
        },
      ],
    });

    final spot = content.byStopId['stop-a'];
    expect(spot, isNotNull);
    expect(spot!.comment, '川沿いが気持ちいい');
    expect(spot.images.single.file, 'river.jpg');
  });

  test('rejects missing fields instead of filling defaults', () {
    expect(
      () => ExploreEditorialContent.fromJson({
        'spots': [
          {
            'stop_id': 'stop-a',
            'comment': 'comment',
          },
        ],
      }),
      throwsFormatException,
    );
  });

  test('rejects duplicate stop ids', () {
    expect(
      () => ExploreEditorialContent.fromJson({
        'spots': [
          {
            'stop_id': 'stop-a',
            'comment': 'first',
            'images': <dynamic>[],
          },
          {
            'stop_id': 'stop-a',
            'comment': 'second',
            'images': <dynamic>[],
          },
        ],
      }),
      throwsFormatException,
    );
  });
}
