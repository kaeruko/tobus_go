import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/providers/route_search_provider.dart';
import 'package:toeigo/services/route_search_service.dart';

class _RecordingRouteSearchService implements RouteSearchService {
  int callCount = 0;
  Completer<RouteSearchResult>? completer;

  @override
  Future<RouteSearchResult> search(RouteSearchRequest request) {
    callCount++;
    final pending = completer;
    if (pending != null) return pending.future;
    throw StateError('unexpected route search call');
  }
}

RouteSearchResult _emptyResult() {
  return RouteSearchResult(
    candidates: const [],
    meta: RouteMeta(
      destinationReachable: true,
      destinationLabel: '目的地',
    ),
    fareByCandidateId: const {},
  );
}

void main() {
  test('片方だけ入力済みなら検索せず入力待ち状態を維持する', () async {
    final service = _RecordingRouteSearchService();
    final notifier = RouteSearchNotifier(service);

    notifier.setFrom('35.7101,139.8107', name: '東京スカイツリー');
    await notifier.triggerSearch();

    expect(service.callCount, 0);
    expect(notifier.state.hasSearched, isFalse);
    expect(notifier.state.isLoading, isFalse);
    expect(notifier.state.errorMessage, isNull);
    expect(notifier.state.candidates, isEmpty);
  });

  test('地点を編集すると以前の検索エラーを消して入力待ちへ戻る', () async {
    final service = _RecordingRouteSearchService();
    final notifier = RouteSearchNotifier(service);

    notifier.setFrom('not-a-coordinate', name: '入力途中');
    notifier.setTo('35.7148,139.7967', name: '浅草寺');
    await notifier.triggerSearch();

    expect(notifier.state.hasSearched, isTrue);
    expect(notifier.state.errorMessage, isNotNull);

    notifier.setFrom('35.7101,139.8107', name: '東京スカイツリー');

    expect(notifier.state.hasSearched, isFalse);
    expect(notifier.state.isLoading, isFalse);
    expect(notifier.state.errorMessage, isNull);
    expect(notifier.state.candidates, isEmpty);
  });

  test('検索中に地点を編集したら古い検索結果を反映しない', () async {
    final service = _RecordingRouteSearchService();
    service.completer = Completer<RouteSearchResult>();
    final notifier = RouteSearchNotifier(service);

    notifier.setFrom('35.7101,139.8107', name: '東京スカイツリー');
    notifier.setTo('35.7148,139.7967', name: '浅草寺');
    final searchFuture = notifier.triggerSearch();

    expect(service.callCount, 1);
    expect(notifier.state.isLoading, isTrue);

    notifier.setFrom('押上', name: '押上');
    expect(notifier.state.isLoading, isFalse);
    expect(notifier.state.hasSearched, isFalse);

    service.completer!.complete(_emptyResult());
    await searchFuture;

    expect(notifier.state.from, '押上');
    expect(notifier.state.hasSearched, isFalse);
    expect(notifier.state.errorMessage, isNull);
    expect(notifier.state.candidates, isEmpty);
  });
}
