import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/api_client.dart';
import '../models/route_models.dart';

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

class RouteSearchNotifier extends StateNotifier<RouteSearchState> {
  RouteSearchNotifier() : super(const RouteSearchState());

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
    // Stop any previous polling
    _generation++;
    final currentGen = _generation;

    if (state.from.isEmpty || state.to.isEmpty) {
      return;
    }

    state = state.copyWith(
      isLoading: true,
      hasSearched: true, // Mark as searched so UI can show loading/results
      errorMessage: null,
      candidates: [],
      meta: null,
    );

    try {
      final fromParts = state.from.split(',');
      final toParts = state.to.split(',');

      if (fromParts.length != 2 || toParts.length != 2) {
        state = state.copyWith(isLoading: false, errorMessage: "出発地または到着地が不正です (lat,lon形式である必要があります)");
        return;
      }

      final alat = double.tryParse(fromParts[0].trim());
      final alon = double.tryParse(fromParts[1].trim());
      final blat = double.tryParse(toParts[0].trim());
      final blon = double.tryParse(toParts[1].trim());

      if (alat == null || alon == null || blat == null || blon == null) {
        state = state.copyWith(isLoading: false, errorMessage: "座標のパースに失敗しました");
        return;
      }

      final searchTime = state.startTime ?? DateTime.now();

      final body = {
        'alat': alat.toString(),
        'alon': alon.toString(),
        'blat': blat.toString(),
        'blon': blon.toString(),
        'pref': state.pref ?? 'fewTransfers',
        'start_time': "${searchTime.hour.toString().padLeft(2, '0')}:${searchTime.minute.toString().padLeft(2, '0')}",
        'target_date_str': "${searchTime.year}-${searchTime.month.toString().padLeft(2, '0')}-${searchTime.day.toString().padLeft(2, '0')}",
      };

      // Changed: POST returns result directly (synchronously)
      // No more job polling.
      final r = await ApiClient.post('/route', body: body);

      // Check for cancellation
      if (_generation != currentGen) return;

      // Parse result immediately
      final candidatesList = r['candidates'] as List? ?? [];
      final metaMap = r['meta'] as Map<String, dynamic>? ?? {};

      final meta = RouteMeta.fromJson(metaMap);
      final candidates = candidatesList
          .map((e) {
            final map = Map<String, dynamic>.from(e as Map);
            if (map['destination_name'] == null || map['destination_name'] == '') {
              map['destination_name'] = state.toName;
            }
            if (map['origin_name'] == null || map['origin_name'] == '') {
              map['origin_name'] = state.fromName;
            }
            return Candidate.fromJson(map);
          })
          .toList();

      state = state.copyWith(
          isLoading: false,
          meta: meta,
          candidates: candidates,
      );
    } catch (e, st) {
      if (_generation != currentGen) return;
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
      // Log error if needed
      print('[RouteSearch] Error executing search: $e $st');
    }
  }
}

final routeSearchProvider = StateNotifierProvider<RouteSearchNotifier, RouteSearchState>((ref) {
  return RouteSearchNotifier();
});
