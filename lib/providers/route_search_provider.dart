import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../models/route_models.dart';
import '../services/route_search_service.dart';

class RouteSearchState {
  final String from;
  final String to;
  final String fromName;
  final String toName;
  final String? pref;
  final DateTime? startTime;
  final bool isLoading;
  final bool hasSearched;
  final String? jobId;
  final List<Candidate> candidates;
  final RouteMeta? meta;
  final String? errorMessage;

  const RouteSearchState({
    this.from = '',
    this.to = '',
    this.fromName = '',
    this.toName = '',
    this.pref,
    this.startTime,
    this.isLoading = false,
    this.hasSearched = false,
    this.jobId,
    this.candidates = const [],
    this.meta,
    this.errorMessage,
  });

  RouteSearchState copyWith({
    String? from,
    String? to,
    String? fromName,
    String? toName,
    String? pref,
    DateTime? startTime,
    bool? isLoading,
    bool? hasSearched,
    String? jobId,
    List<Candidate>? candidates,
    RouteMeta? meta,
    String? errorMessage,
  }) {
    return RouteSearchState(
      from: from ?? this.from,
      to: to ?? this.to,
      fromName: fromName ?? this.fromName,
      toName: toName ?? this.toName,
      pref: pref ?? this.pref,
      startTime: startTime ?? this.startTime,
      isLoading: isLoading ?? this.isLoading,
      hasSearched: hasSearched ?? this.hasSearched,
      jobId: jobId ?? this.jobId,
      candidates: candidates ?? this.candidates,
      meta: meta ?? this.meta,
      errorMessage: errorMessage ?? this.errorMessage,
    );
  }
}

final routeSearchServiceProvider = Provider<RouteSearchService>((ref) {
  return const ApiRouteSearchService();
});

class RouteSearchNotifier extends StateNotifier<RouteSearchState> {
  final RouteSearchService _routeSearchService;

  RouteSearchNotifier(this._routeSearchService) : super(const RouteSearchState());

  int _generation = 0;

  void setFrom(String from, {String? name}) {
    state = state.copyWith(from: from, fromName: name ?? from);
  }

  void setTo(String to, {String? name}) {
    state = state.copyWith(to: to, toName: name ?? to);
  }

  void setPref(String pref) {
    state = state.copyWith(pref: pref);
  }

  void setStartTime(DateTime? startTime) {
    state = state.copyWith(startTime: startTime);
  }

  Future<void> triggerSearch() async {
    _generation++;
    final currentGen = _generation;

    final from = state.from.trim();
    final to = state.to.trim();
    if (from.isEmpty || to.isEmpty) {
      state = state.copyWith(
        isLoading: false,
        hasSearched: true,
        errorMessage: '出発地と到着地の両方を指定してください',
        candidates: [],
        meta: null,
      );
      return;
    }

    state = state.copyWith(
      isLoading: true,
      hasSearched: true,
      errorMessage: null,
      candidates: [],
      meta: null,
    );

    try {
      final origin = _parsePoint(from, label: '出発地');
      final destination = _parsePoint(to, label: '到着地');
      final searchTime = state.startTime ?? DateTime.now();

      final result = await _routeSearchService.search(
        RouteSearchRequest(
          origin: origin,
          destination: destination,
          originName: state.fromName,
          destinationName: state.toName,
          startTime: searchTime,
          preference: state.pref,
        ),
      );

      if (_generation != currentGen) return;

      state = state.copyWith(
        isLoading: false,
        meta: result.meta,
        candidates: result.candidates,
      );
    } catch (error, stackTrace) {
      if (_generation != currentGen) return;
      state = state.copyWith(
        isLoading: false,
        errorMessage: error.toString(),
        candidates: [],
        meta: null,
      );
      print('[RouteSearch] Error executing search: $error $stackTrace');
    }
  }

  LatLng _parsePoint(String value, {required String label}) {
    final parts = value.split(',');
    if (parts.length != 2) {
      throw FormatException(
        '$labelが不正です (lat,lon形式である必要があります): $value',
      );
    }

    final lat = double.tryParse(parts[0].trim());
    final lon = double.tryParse(parts[1].trim());
    if (lat == null || lon == null) {
      throw FormatException('$labelの座標をパースできません: $value');
    }
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      throw RangeError('$labelの座標が範囲外です: $value');
    }

    return LatLng(lat, lon);
  }
}

final routeSearchProvider =
    StateNotifierProvider<RouteSearchNotifier, RouteSearchState>((ref) {
      return RouteSearchNotifier(ref.watch(routeSearchServiceProvider));
    });
