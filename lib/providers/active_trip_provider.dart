import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';

class ActiveTripNotifier extends StateNotifier<AsyncValue<Trip?>> {
  ActiveTripNotifier() : super(const AsyncValue.loading()) {
    refresh();
  }

  final TripService _tripService = TripService();
  StreamSubscription<Trip?>? _sub;

  Future<void> refresh() async {
    state = const AsyncValue.loading();

    await _sub?.cancel();
    _sub = _tripService.streamActiveTrip().listen(
      (trip) {
        state = AsyncValue.data(trip);
      },
      onError: (e, st) {
        state = AsyncValue.error(e, st);
      },
    );
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }
}

final activeTripProvider = StateNotifierProvider<ActiveTripNotifier, AsyncValue<Trip?>>((ref) {
  final notifier = ActiveTripNotifier();
  ref.onDispose(notifier.dispose);
  return notifier;
});
