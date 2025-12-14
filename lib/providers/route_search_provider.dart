import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/api_client.dart';
import '../models/route_models.dart';

class RouteSearchState {
  final String from;
  final String to;
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

  void setFrom(String from) {
    state = state.copyWith(from: from);
  }

  void setTo(String to) {
    state = state.copyWith(to: to);
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
      final body = {
        'from': state.from,
        'to': state.to,
      };
      if (state.pref != null) {
        body['preference'] = state.pref!;
      }
      if (state.startTime != null) {
        body['start_time'] = state.startTime!.toIso8601String();
      }

      final r = await ApiClient.post('/jobs', body: body);
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
        final r = await ApiClient.get('/jobs/$jobId');

        if (_generation != generation) return;

        final status = r['status'] as String;
        if (status == 'computing') {
            // continue polling
            continue;
        } else if (status == 'done') {
            final result = r['result'] as Map<String, dynamic>;
            final meta = RouteMeta.fromJson(result['meta'] as Map<String, dynamic>);
            final candidates = (result['candidates'] as List)
                .map((e) => Candidate.fromJson(e as Map<String, dynamic>))
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
