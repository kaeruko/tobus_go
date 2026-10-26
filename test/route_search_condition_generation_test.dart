import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/fare_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/transport_scope.dart';
import 'package:toeigo/providers/route_search_provider.dart';
import 'package:toeigo/services/route_search_service.dart';

class _ControlledSearchService implements RouteSearchService {
  final requests = <RouteSearchRequest>[];
  final pending = <Completer<RouteSearchResult>>[];

  @override
  Future<RouteSearchResult> search(RouteSearchRequest request) {
    requests.add(request);
    final completer = Completer<RouteSearchResult>();
    pending.add(completer);
    return completer.future;
  }
}

final _departure = DateTime(2099, 10, 12, 10);
final _nextDeparture = DateTime(2099, 10, 13, 11);

RouteSearchResult _result(String id) => RouteSearchResult(
  candidates: [
    Candidate(
      id: id,
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 0,
      totalTime: 0,
      steps: const [],
      points: const [],
    ),
  ],
  meta: RouteMeta(destinationReachable: true, destinationLabel: id),
  fareByCandidateId: {
    id: const FareQuote(
      normalFareYen: 210,
      payNowYen: 210,
      effectiveFareYen: 210,
      policyId: 'normal',
      settlementType: 'normal',
      status: 'available',
    ),
  },
);

RouteSearchNotifier _prepare(_ControlledSearchService service) {
  final notifier = RouteSearchNotifier(service);
  addTearDown(notifier.dispose);
  notifier.setFrom(
    '35.69,139.78',
    name: 'Origin display',
    nameJa: '始点',
    nameEn: 'Origin',
  );
  notifier.setTo(
    '35.71,139.80',
    name: 'Destination display',
    nameJa: '終点',
    nameEn: 'Destination',
  );
  notifier.setPref('cost');
  notifier.setStartTime(_departure);
  return notifier;
}

void _expectInputPreserved(RouteSearchState state, String changed) {
  expect(state.from, '35.69,139.78');
  expect(state.to, '35.71,139.80');
  expect(state.fromName, 'Origin display');
  expect(state.toName, 'Destination display');
  expect(state.fromNameJa, '始点');
  expect(state.toNameJa, '終点');
  expect(state.fromNameEn, 'Origin');
  expect(state.toNameEn, 'Destination');
  expect(state.pref, changed == 'preference' ? 'shortTime' : 'cost');
  expect(state.busOnly, changed == 'transport');
  expect(
    state.acceptExperimentalTransferModel,
    changed == 'estimated transfer',
  );
  expect(
    state.startTime,
    changed == 'departure'
        ? _nextDeparture
        : changed == 'cleared departure'
        ? null
        : _departure,
  );
}

void _expectWaitingForSearch(RouteSearchState state) {
  expect(state.isLoading, isFalse);
  expect(state.hasSearched, isFalse);
  expect(state.candidates, isEmpty);
  expect(state.fareByCandidateId, isEmpty);
  expect(state.meta, isNull);
  expect(state.errorMessage, isNull);
}

void main() {
  final changes = <String, void Function(RouteSearchNotifier)>{
    'preference': (notifier) => notifier.setPref('shortTime'),
    'transport': (notifier) => notifier.setBusOnly(true),
    'departure': (notifier) => notifier.setStartTime(_nextDeparture),
    'cleared departure': (notifier) => notifier.setStartTime(null),
    'estimated transfer': (notifier) =>
        notifier.setExperimentalTransferConsent(true),
  };

  for (final change in changes.entries) {
    test(
      '${change.key} change ignores a pending success before the next search',
      () async {
        final service = _ControlledSearchService();
        final notifier = _prepare(service);
        final pending = notifier.triggerSearch();
        change.value(notifier);

        service.pending.single.complete(_result('obsolete'));
        await pending;

        _expectWaitingForSearch(notifier.state);
        _expectInputPreserved(notifier.state, change.key);
        expect(service.requests, hasLength(1));
      },
    );

    test(
      '${change.key} change ignores a pending failure before the next search',
      () async {
        final service = _ControlledSearchService();
        final notifier = _prepare(service);
        final pending = notifier.triggerSearch();
        change.value(notifier);

        service.pending.single.completeError(StateError('obsolete failure'));
        await pending;

        _expectWaitingForSearch(notifier.state);
        _expectInputPreserved(notifier.state, change.key);
        expect(service.requests, hasLength(1));
      },
    );

    test(
      '${change.key} change clears completed results and keeps the other criteria',
      () async {
        final service = _ControlledSearchService();
        final notifier = _prepare(service);
        final pending = notifier.triggerSearch();
        service.pending.single.complete(_result('completed'));
        await pending;
        expect(notifier.state.candidates.single.id, 'completed');
        expect(notifier.state.fareByCandidateId.keys, ['completed']);

        change.value(notifier);

        _expectWaitingForSearch(notifier.state);
        _expectInputPreserved(notifier.state, change.key);
      },
    );
  }

  test('empty transport scope blocks search before service access', () async {
    final service = _ControlledSearchService();
    final notifier = _prepare(service);

    expect(notifier.state.transportScope, TransportServiceId.legacyDefault);
    notifier.setTransportEnabled(TransportServiceId.toeiBus, false);
    notifier.setTransportEnabled(TransportServiceId.toeiSubway, false);
    expect(notifier.state.transportScope, isEmpty);

    await notifier.triggerSearch();

    expect(service.requests, isEmpty);
    _expectWaitingForSearch(notifier.state);
  });

  test('same criteria keep pending and completed searches intact', () async {
    final service = _ControlledSearchService();
    final notifier = _prepare(service);
    final pending = notifier.triggerSearch();
    final loadingState = notifier.state;
    notifier.setPref('cost');
    notifier.setBusOnly(false);
    notifier.setExperimentalTransferConsent(false);
    notifier.setStartTime(DateTime(2099, 10, 12, 10));
    expect(notifier.state, same(loadingState));

    service.pending.single.complete(_result('current'));
    await pending;
    expect(notifier.state.candidates.single.id, 'current');
    final completedState = notifier.state;
    notifier.setPref('cost');
    notifier.setBusOnly(false);
    notifier.setStartTime(_departure);
    expect(notifier.state, same(completedState));
  });

  test(
    'clearing a fixed departure sends current time and null remains a no-op',
    () async {
      final service = _ControlledSearchService();
      final notifier = _prepare(service);
      notifier.setStartTime(null);
      expect(notifier.state.startTime, isNull);
      // Updating another field must keep the explicit clear.
      expect(notifier.state.copyWith(busOnly: true).startTime, isNull);
      final clearedState = notifier.state;
      notifier.setStartTime(null);
      expect(notifier.state, same(clearedState));

      final before = DateTime.now().subtract(const Duration(seconds: 1));
      final pending = notifier.triggerSearch();
      final after = DateTime.now().add(const Duration(seconds: 1));
      final request = service.requests.single;
      expect(request.startTime.isBefore(before), isFalse);
      expect(request.startTime.isAfter(after), isFalse);
      expect(request.preference, 'cost');
      expect(request.busOnly, isFalse);
      expect(request.acceptExperimentalTransferModel, isFalse);
      expect(request.originName, '始点');
      expect(request.destinationNameEn, 'Destination');
      final loadingState = notifier.state;
      notifier.setStartTime(null);
      expect(notifier.state, same(loadingState));
      service.pending.single.complete(_result('current-time'));
      await pending;
      expect(notifier.state.candidates.single.id, 'current-time');
    },
  );

  test('a condition change clears an already displayed search error', () async {
    final service = _ControlledSearchService();
    final notifier = _prepare(service);
    final pending = notifier.triggerSearch();
    service.pending.single.completeError(StateError('current failure'));
    await pending;
    expect(notifier.state.errorMessage, contains('current failure'));

    notifier.setPref('shortTime');

    _expectWaitingForSearch(notifier.state);
    _expectInputPreserved(notifier.state, 'preference');
  });

  test(
    'explicit estimated-transfer choice is sent and is never enabled after an empty result',
    () async {
      final service = _ControlledSearchService();
      final notifier = _prepare(service);
      notifier.setExperimentalTransferConsent(true);

      final pending = notifier.triggerSearch();
      expect(service.requests.single.acceptExperimentalTransferModel, isTrue);
      service.pending.single.complete(
        RouteSearchResult(
          candidates: const [],
          meta: RouteMeta(destinationReachable: true, destinationLabel: 'none'),
          fareByCandidateId: const {},
        ),
      );
      await pending;

      expect(notifier.state.acceptExperimentalTransferModel, isTrue);
      expect(notifier.state.candidates, isEmpty);
      notifier.setExperimentalTransferConsent(false);
      expect(notifier.state.acceptExperimentalTransferModel, isFalse);
    },
  );
}
