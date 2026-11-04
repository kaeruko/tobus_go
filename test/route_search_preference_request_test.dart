import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/transport_scope.dart';
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

  test('saved Metro route restores its explicit search context', () async {
    final service = _RecordingSearchService();
    final notifier = prepare(service);
    notifier.prepareSavedRoute(
      from: '35.6580,139.7016',
      to: '35.7107,139.7976',
      fromName: '渋谷',
      toName: '浅草',
      fromNameJa: '渋谷',
      toNameJa: '浅草',
      fromNameEn: 'Shibuya',
      toNameEn: 'Asakusa',
      startTime: departure,
      transportScope: const {TransportServiceId.tokyoMetro},
      acceptExperimentalTransferModel: true,
    );

    await notifier.triggerSearch();

    expect(notifier.state.transportScope, {TransportServiceId.tokyoMetro});
    expect(notifier.state.acceptExperimentalTransferModel, isTrue);
    expect(service.body?['transport_scope'], [TransportServiceId.tokyoMetro]);
    expect(service.body?['accept_experimental_transfer_model'], isTrue);
  });

  test(
    'Kita-ayase to Shibuya Metro search implicitly enables estimated transfers',
    () async {
      final service = _RecordingSearchService();
      final notifier = prepare(service);
      notifier.setFrom('35.7770135,139.8321012', name: '北綾瀬駅');
      notifier.setTo('35.6580339,139.7016358', name: '渋谷駅');
      notifier.setTransportEnabled(TransportServiceId.toeiBus, false);
      notifier.setTransportEnabled(TransportServiceId.toeiSubway, false);
      notifier.setTransportEnabled(TransportServiceId.tokyoMetro, true);
      notifier.setStartTime(DateTime(2026, 11, 5, 12, 38));

      await notifier.triggerSearch();

      expect(service.body?['transport_scope'], [TransportServiceId.tokyoMetro]);
      expect(service.body?['start_time'], '12:38');
      expect(service.body?['target_date_str'], '2026-11-05');
      expect(service.body?['pref'], 'fewTransfers');
      expect(service.body?['accept_experimental_transfer_model'], isTrue);
    },
  );

  test('saved Metro search enables estimates even if previously saved as off', () async {
    final service = _RecordingSearchService();
    final notifier = prepare(service);
    notifier.prepareSavedRoute(
      from: '35.7770135,139.8321012',
      to: '35.6580339,139.7016358',
      fromName: '北綾瀬駅',
      toName: '渋谷駅',
      fromNameJa: '北綾瀬駅',
      toNameJa: '渋谷駅',
      fromNameEn: 'Kita-ayase',
      toNameEn: 'Shibuya',
      startTime: DateTime(2026, 11, 5, 12, 38),
      transportScope: const {TransportServiceId.tokyoMetro},
      acceptExperimentalTransferModel: false,
    );

    await notifier.triggerSearch();

    expect(service.body?['transport_scope'], [TransportServiceId.tokyoMetro]);
    expect(service.body?['accept_experimental_transfer_model'], isTrue);
  });

  test('ordinary Toei-only searches do not enable estimated Metro transfers', () async {
    final service = _RecordingSearchService();
    final notifier = prepare(service);

    await notifier.triggerSearch();

    expect(service.body?['transport_scope'], ['toei_bus', 'toei_subway']);
    expect(service.body, isNot(contains('accept_experimental_transfer_model')));
  });

  test('legacy saved route uses legacy scope and estimated transfers off', () {
    final service = _RecordingSearchService();
    final notifier = prepare(service);
    notifier.setExperimentalTransferConsent(true);

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

    expect(notifier.state.transportScope, TransportServiceId.legacyDefault);
    expect(notifier.state.acceptExperimentalTransferModel, isFalse);
  });

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
