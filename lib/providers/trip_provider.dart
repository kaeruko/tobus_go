import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';
import 'app_session_provider.dart';

final tripStreamProvider = StreamProvider.autoDispose<Trip?>((ref) {
  final session = ref.watch(appSessionProvider);
  final tripId = session.currentTripId;

  if (tripId == null) {
    return Stream.value(null);
  }

  return TripService().streamTrip(tripId);
});
