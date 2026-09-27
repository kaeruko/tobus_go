import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  Map<String, dynamic> candidateJson({
    required int waitMinutes,
    required String waitDeparture,
    required String waitArrival,
  }) {
    return {
      'id': 'wait-precision',
      'lines': ['上23'],
      'rides': 1,
      'walking_distance_meters': 219,
      'walking_segment_count': 1,
      'boards': 1,
      'transfers': 0,
      'total': 15,
      'total_time': 15,
      'origin_name': '押上',
      'origin_name_en': 'Oshiage',
      'destination_name': '上野駅',
      'destination_name_en': 'Ueno Station',
      'steps': [
        {
          'step_id': 'walk-1',
          'kind': 'walk',
          'title': '徒歩',
          'from_': '現在地',
          'to': '平井七丁目',
          'minutes': 3,
          'meters': 219.0,
        },
        {
          'step_id': 'wait-1',
          'kind': 'wait',
          'title': '待ち時間',
          'from_': '平井七丁目',
          'to': '平井七丁目',
          'minutes': waitMinutes,
          'meters': 0.0,
          'departure_time': waitDeparture,
          'arrival_time': waitArrival,
        },
        {
          'step_id': 'bus-1',
          'kind': 'bus',
          'title': '上23 上野松坂屋前行',
          'from_': '平井七丁目',
          'to': '社会福祉会館前',
          'minutes': 10,
          'meters': 0.0,
          'departure_time': waitArrival,
          'arrival_time': '07:43',
        },
      ],
    };
  }

  test('normalizes the known one-minute wait precision gap', () {
    final candidate = Candidate.fromJson(
      candidateJson(
        waitMinutes: 2,
        waitDeparture: '07:30',
        waitArrival: '07:33',
      ),
    );

    expect(candidate.steps[0].kind, 'wait');
    expect(candidate.steps[0].minutes, 3);
    expect(candidate.steps[0].departureTime, '07:27');
    expect(candidate.steps[0].arrivalTime, '07:30');

    expect(candidate.steps[1].kind, 'walk');
    expect(candidate.steps[1].departureTime, '07:30');
    expect(candidate.steps[1].arrivalTime, '07:33');
  });

  test('leading wait keeps English origin after wait/walk normalization', () {
    final candidate = Candidate.fromJson(
      candidateJson(
        waitMinutes: 2,
        waitDeparture: '07:30',
        waitArrival: '07:33',
      ),
    );

    final wait = candidate.steps[0];
    final walk = candidate.steps[1];

    expect(wait.kind, 'wait');
    expect(wait.place, '押上');
    expect(wait.placeEn, 'Oshiage');
    expect(wait.fromNameEn, 'Oshiage');
    expect(wait.toNameEn, 'Oshiage');

    expect(walk.kind, 'walk');
    expect(walk.fromName, '押上');
    expect(walk.fromNameEn, 'Oshiage');
  });

  test('still fails fast when the wait mismatch exceeds one minute', () {
    expect(
      () => Candidate.fromJson(
        candidateJson(
          waitMinutes: 2,
          waitDeparture: '07:29',
          waitArrival: '07:33',
        ),
      ),
      throwsStateError,
    );
  });
}
