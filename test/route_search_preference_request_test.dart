import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/providers/route_search_provider.dart';
import 'package:toeigo/services/route_search_service.dart';

class _RecordingSearchService implements RouteSearchService {
  Map<String, dynamic>? body;

  @override
  Future<RouteSearchResult> search(RouteSearchRequest request) async {
    body = request.toApiBody();
    return RouteSearchResult(
      candidates: const [],
      meta: RouteMeta(destinationReachable: true, destinationLabel: '渋谷区'),
      fareByCandidateId: const {},
    );
  }
}

void main() {
  final departure = DateTime(2026, 10, 6, 7, 46);

  RouteSearchNotifier prepare(_RecordingSearchService service) {
    final notifier = RouteSearchNotifier(service);
    addTearDown(notifier.dispose);
    notifier.setFrom('35.708166,139.817434', name: '十間橋');
    notifier.setTo('35.6636842,139.6977409', name: '渋谷区');
    notifier.setStartTime(departure);
    return notifier;
  }

  void expectRequest(_RecordingSearchService service, String preference) {
    expect(service.body?['pref'], preference);
    expect(service.body?['start_time'], '07:46');
    expect(service.body?['target_date_str'], '2026-10-06');
    expect(service.body?['bus_only'], isFalse);
  }

  test(
    'untouched preference sends the displayed few-transfers default',
    () async {
      final service = _RecordingSearchService();
      final notifier = prepare(service);

      await notifier.triggerSearch();

      expectRequest(service, 'fewTransfers');
      expect(notifier.state.errorMessage, isNull);
    },
  );

  test(
    'saved route without a preference sends the displayed default',
    () async {
      final service = _RecordingSearchService();
      final notifier = prepare(service);
      notifier.prepareSavedRoute(
        from: '35.708166,139.817434',
        to: '35.6636842,139.6977409',
        fromName: '十間橋',
        toName: '渋谷区',
        fromNameJa: '十間橋',
        toNameJa: '渋谷区',
        fromNameEn: 'Jukkembashi',
        toNameEn: 'Shibuya',
        startTime: departure,
      );

      await notifier.triggerSearch();

      expectRequest(service, 'fewTransfers');
    },
  );

  test('explicit short-time selection sends time', () async {
    final service = _RecordingSearchService();
    final notifier = prepare(service);
    notifier.setPref('shortTime');

    await notifier.triggerSearch();

    expectRequest(service, 'time');
  });

  test('explicit cost preference remains cost', () async {
    final service = _RecordingSearchService();
    final notifier = prepare(service);
    notifier.setPref('cost');

    await notifier.triggerSearch();

    expectRequest(service, 'cost');
  });
}
