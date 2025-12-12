import '../data/global_state.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import 'trip_service.dart';

enum TripDirection { outbound, inbound }

/// 行き・帰りの経路を一時保存し、往復が揃った時にTripを作成するための薄いサービス。
class TripDraftService {
  TripDraft get _draft => kTripDraft;

  Candidate? get outbound => _draft.outbound;
  Candidate? get inbound => _draft.inbound;

  bool get isComplete => _draft.isComplete;

  void setRoute(TripDirection direction, Candidate route) {
    if (direction == TripDirection.outbound) {
      _draft.outbound = route;
    } else {
      _draft.inbound = route;
    }
  }

  void clearDirection(TripDirection direction) {
    if (direction == TripDirection.outbound) {
      _draft.outbound = null;
    } else {
      _draft.inbound = null;
    }
  }

  void reset() => _draft.clear();

  List<Candidate> currentRoutes() => _draft.toRoutes();

  Future<String> createTrip() async {
    if (!isComplete) {
      throw StateError('行きと帰りの経路を両方選んでください');
    }

    final outboundRoute = _draft.outbound!;
    final inboundRoute = _draft.inbound!;

    final schedule = createRoundTripSchedule(
      outbound: outboundRoute,
      inbound: inboundRoute,
    );

    final tripId = await TripService().createTrip(
      [outboundRoute, inboundRoute],
      schedule,
    );

    reset();
    return tripId;
  }
}
