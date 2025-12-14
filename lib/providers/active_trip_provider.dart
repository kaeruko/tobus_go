import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';

class ActiveTripNotifier extends StateNotifier<AsyncValue<Trip?>> {
  ActiveTripNotifier() : super(const AsyncValue.loading()) {
    refresh();
  }

  final TripService _tripService = TripService();

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    try {
      final trip = await _tripService.getActiveTrip();
      state = AsyncValue.data(trip);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }
}

final activeTripProvider = StateNotifierProvider<ActiveTripNotifier, AsyncValue<Trip?>>((ref) {
  return ActiveTripNotifier();
});
