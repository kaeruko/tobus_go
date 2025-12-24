import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/route_models.dart';
import '../models/leg_models.dart';
import '../models/group_models.dart';
import '../services/trip_service.dart';

class TripDraftState {
  final Candidate? outbound;
  final Candidate? inbound;

  const TripDraftState({this.outbound, this.inbound});

  bool get isComplete => outbound != null && inbound != null;

  TripDraftState copyWith({Candidate? outbound, Candidate? inbound}) {
    return TripDraftState(
      outbound: outbound ?? this.outbound,
      inbound: inbound ?? this.inbound,
    );
  }
}

class TripDraftNotifier extends StateNotifier<TripDraftState> {
  TripDraftNotifier() : super(const TripDraftState());

  void setRoute(LegDirection direction, Candidate route) {
    if (direction == LegDirection.outbound) {
      state = TripDraftState(outbound: route, inbound: state.inbound);
    } else if (direction == LegDirection.inbound) {
      state = TripDraftState(outbound: state.outbound, inbound: route);
    }
  }

  void reset() {
    state = const TripDraftState();
  }

  Future<String> createTrip() async {
    if (!state.isComplete) {
      throw StateError('行きと帰りの経路を両方選んでください');
    }
    
    // Create configured legs
    final legs = [
        Leg(candidate: state.outbound!, direction: LegDirection.outbound, status: LegStatus.confirmed),
        Leg(candidate: state.inbound!, direction: LegDirection.inbound, status: LegStatus.confirmed),
    ];
    
    final schedule = createScheduleFromLegs(legs, userSelectedStartTime: state.outbound?.departureDate);
    
    final tripId = await TripService().createTrip(legs, schedule);
    
    reset();
    return tripId;
  }
}

final tripDraftProvider = StateNotifierProvider<TripDraftNotifier, TripDraftState>((ref) {
  return TripDraftNotifier();
});
