import '../data/global_state.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/leg_models.dart';
import 'trip_service.dart';

/// 行き・帰りの経路を一時保存し、往復が揃った時にTripを作成するための薄いサービス。
class TripDraftService {
  TripDraft get _draft => kTripDraft;

  Candidate? get outbound => _draft.outbound;
  Candidate? get inbound => _draft.inbound;

  bool get isComplete => _draft.isComplete;

  void setRoute(LegDirection direction, Candidate route) => _draft.setLeg(direction, route);

  void clearDirection(LegDirection direction) => _draft.clearDirection(direction);

  void reset() => _draft.clear();

  List<Leg> currentLegs() => _draft.toLegs();

  Future<String> createTrip() async {
    if (!isComplete) {
      throw StateError('行きと帰りの経路を両方選んでください');
    }

    final legs = _draft.toLegs();
    final outboundRoute = legs.firstWhere((e) => e.direction == LegDirection.outbound).candidate;
    final inboundRoute = legs.firstWhere((e) => e.direction == LegDirection.inbound).candidate;

    final schedule = createScheduleFromLegs(legs);

    final tripId = await TripService().createTrip(legs, schedule);

    reset();
    return tripId;
  }
}
