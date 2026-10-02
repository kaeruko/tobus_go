import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../models/fare_models.dart';
import '../models/route_models.dart';
import '../services/route_search_service.dart';

class RouteSearchState {
  final String from;
  final String to;
  final String fromName;
  final String toName;
  final String fromNameJa;
  final String toNameJa;
  final String fromNameEn;
  final String toNameEn;
  final String? pref;
  final bool busOnly;
  final DateTime? startTime;
  final bool isLoading;
  final bool hasSearched;
  final String? jobId;
  final List<Candidate> candidates;
  final Map<String, FareQuote> fareByCandidateId;
  final RouteMeta? meta;
  final String? errorMessage;

  const RouteSearchState({
    this.from = '',
    this.to = '',
    this.fromName = '',
    this.toName = '',
    this.fromNameJa = '',
    this.toNameJa = '',
    this.fromNameEn = '',
    this.toNameEn = '',
    this.pref,
    this.busOnly = false,
    this.startTime,
    this.isLoading = false,
    this.hasSearched = false,
    this.jobId,
    this.candidates = const [],
    this.fareByCandidateId = const {},
    this.meta,
    this.errorMessage,
  });

  RouteSearchState copyWith({
    String? from,
    String? to,
    String? fromName,
    String? toName,
    String? fromNameJa,
    String? toNameJa,
    String? fromNameEn,
    String? toNameEn,
    String? pref,
    bool? busOnly,
    DateTime? startTime,
    bool? isLoading,
    bool? hasSearched,
    String? jobId,
    List<Candidate>? candidates,
    Map<String, FareQuote>? fareByCandidateId,
    RouteMeta? meta,
    String? errorMessage,
    bool clearMeta = false,
    bool clearErrorMessage = false,
  }) {
    return RouteSearchState(
      from: from ?? this.from,
      to: to ?? this.to,
      fromName: fromName ?? this.fromName,
      toName: toName ?? this.toName,
      fromNameJa: fromNameJa ?? this.fromNameJa,
      toNameJa: toNameJa ?? this.toNameJa,
      fromNameEn: fromNameEn ?? this.fromNameEn,
      toNameEn: toNameEn ?? this.toNameEn,
      pref: pref ?? this.pref,
      busOnly: busOnly ?? this.busOnly,
      startTime: startTime ?? this.startTime,
      isLoading: isLoading ?? this.isLoading,
      hasSearched: hasSearched ?? this.hasSearched,
      jobId: jobId ?? this.jobId,
      candidates: candidates ?? this.candidates,
      fareByCandidateId: fareByCandidateId ?? this.fareByCandidateId,
      meta: clearMeta ? null : (meta ?? this.meta),
      errorMessage: clearErrorMessage
          ? null
          : (errorMessage ?? this.errorMessage),
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

  void prepareSavedRoute({
    required String from,
    required String to,
    required String fromName,
    required String toName,
    required String fromNameJa,
    required String toNameJa,
    required String fromNameEn,
    required String toNameEn,
    required DateTime startTime,
    String? preference,
  }) {
    if (from.trim().isEmpty || to.trim().isEmpty) {
      throw ArgumentError('保存経路の始点・終点座標は空にできません');
    }
    if (fromName.trim().isEmpty || toName.trim().isEmpty) {
      throw ArgumentError('保存経路の表示名は空にできません');
    }

    _generation++;
    state = RouteSearchState(
      from: from,
      to: to,
      fromName: fromName,
      toName: toName,
      fromNameJa: fromNameJa,
      toNameJa: toNameJa,
      fromNameEn: fromNameEn,
      toNameEn: toNameEn,
      pref: preference,
      busOnly: false,
      startTime: startTime,
    );
  }

  void setFrom(
    String from, {
    String? name,
    String? nameJa,
    String? nameEn,
  }) {
    _generation++;
    state = state.copyWith(
      from: from,
      fromName: name ?? from,
      fromNameJa: nameJa ?? '',
      fromNameEn: nameEn ?? '',
      isLoading: false,
      hasSearched: false,
      candidates: const [],
      fareByCandidateId: const {},
      clearMeta: true,
      clearErrorMessage: true,
    );
  }

  void setTo(
    String to, {
    String? name,
    String? nameJa,
    String? nameEn,
  }) {
    _generation++;
    state = state.copyWith(
      to: to,
      toName: name ?? to,
      toNameJa: nameJa ?? '',
      toNameEn: nameEn ?? '',
      isLoading: false,
      hasSearched: false,
      candidates: const [],
      fareByCandidateId: const {},
      clearMeta: true,
      clearErrorMessage: true,
    );
  }

  void swapEndpoints() {
    _generation++;
    final current = state;
    state = RouteSearchState(
      from: current.to,
      to: current.from,
      fromName: current.toName,
      toName: current.fromName,
      fromNameJa: current.toNameJa,
      toNameJa: current.fromNameJa,
      fromNameEn: current.toNameEn,
      toNameEn: current.fromNameEn,
      pref: current.pref,
      busOnly: current.busOnly,
      startTime: current.startTime,
      isLoading: false,
      hasSearched: false,
      candidates: const [],
      fareByCandidateId: const {},
    );
  }

  void setPref(String pref) {
    state = state.copyWith(pref: pref);
  }

  void setBusOnly(bool busOnly) {
    state = state.copyWith(busOnly: busOnly);
  }

  void setStartTime(DateTime? startTime) {
    state = state.copyWith(startTime: startTime);
  }

  Future<void> triggerSearch() async {
    _generation++;
    final currentGen = _generation;

    if (state.from.trim().isEmpty || state.to.trim().isEmpty) {
      state = state.copyWith(
        isLoading: false,
        hasSearched: false,
        candidates: const [],
        fareByCandidateId: const {},
        clearMeta: true,
        clearErrorMessage: true,
      );
      return;
    }

    state = state.copyWith(
      isLoading: true,
      hasSearched: true,
      candidates: const [],
      fareByCandidateId: const {},
      clearMeta: true,
      clearErrorMessage: true,
    );

    try {
      final origin = _parsePoint(state.from, label: '出発地');
      final destination = _parsePoint(state.to, label: '到着地');
      final searchTime = state.startTime ?? DateTime.now();

      final result = await _routeSearchService.search(
        RouteSearchRequest(
          origin: origin,
          destination: destination,
          originName: state.fromNameJa.trim().isNotEmpty
              ? state.fromNameJa
              : state.fromName,
          destinationName: state.toNameJa.trim().isNotEmpty
              ? state.toNameJa
              : state.toName,
          originNameEn: state.fromNameEn,
          destinationNameEn: state.toNameEn,
          startTime: searchTime,
          preference: state.pref,
          busOnly: state.busOnly,
        ),
      );

      if (_generation != currentGen) return;

      state = state.copyWith(
        isLoading: false,
        meta: result.meta,
        candidates: result.candidates,
        fareByCandidateId: result.fareByCandidateId,
        clearErrorMessage: true,
      );
    } catch (e, st) {
      if (_generation != currentGen) return;
      state = state.copyWith(
        isLoading: false,
        candidates: const [],
        fareByCandidateId: const {},
        clearMeta: true,
        errorMessage: e.toString(),
      );
      print('[RouteSearch] Error executing search: $e $st');
    }
  }

  LatLng _parsePoint(String value, {required String label}) {
    final parts = value.split(',');
    if (parts.length != 2) {
      throw FormatException('$labelが不正です (lat,lon形式である必要があります): $value');
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
