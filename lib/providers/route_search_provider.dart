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

      final body = {
        'alat': alat.toString(),
        'alon': alon.toString(),
        'blat': blat.toString(),
        'blon': blon.toString(),
        'pref': state.pref ?? 'fewTransfers', // default to fewTransfers if null? or cost? server default is cost
      };

      if (state.startTime != null) {
        // "10:00"
        final h = state.startTime!.hour.toString().padLeft(2, '0');
        final m = state.startTime!.minute.toString().padLeft(2, '0');
        body['time'] = "$h:$m";
        
        // "YYYY-MM-DD"
        final y = state.startTime!.year.toString();
        final mo = state.startTime!.month.toString().padLeft(2, '0');
        final d = state.startTime!.day.toString().padLeft(2, '0');
        body['date'] = "$y-$mo-$d";
      }

      final r = await ApiClient.post('/route', body: body);
      final jobId = r['job_id'] as String;

      // Check if cancelled
      if (_generation != currentGen) return;

      state = state.copyWith(jobId: jobId);

      _poll(jobId, currentGen);
    } catch (e, st) {
      if (_generation != currentGen) return;
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
      // Log error if needed
      print('[RouteSearch] Error starting job: $e $st');
    }
  }

  Future<void> _poll(String jobId, int generation) async {
    while (true) {
      if (_generation != generation) return;

      await Future.delayed(const Duration(milliseconds: 600));

      if (_generation != generation) return;

      try {
        final r = await ApiClient.get('/route', params: {'job_id': jobId});

        if (_generation != generation) return;

        final status = r['status'] as String;
        if (status == 'computing' || status == 'running' || status == 'pending') {
            // continue polling
            continue;
        } else if (status == 'done') {
            final result = r['result'] as Map<String, dynamic>;
            final meta = RouteMeta.fromJson(result['meta'] as Map<String, dynamic>);
            final candidates = (result['candidates'] as List)
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
            return;
        } else if (status == 'error') {
            final msg = r['error'] ?? 'Unknown error';
            state = state.copyWith(
                isLoading: false,
                errorMessage: msg.toString(),
            );
            return;
        } else {
            // Unknown status, stop polling to avoid infinite loop
            state = state.copyWith(
                isLoading: false,
                errorMessage: 'Unknown job status: $status',
            );
            return;
        }
      } catch (e) {
        if (_generation != generation) return;
        state = state.copyWith(isLoading: false, errorMessage: e.toString());
        return;
      }
    }
  }
}

final routeSearchProvider = StateNotifierProvider<RouteSearchNotifier, RouteSearchState>((ref) {
  return RouteSearchNotifier();
});
