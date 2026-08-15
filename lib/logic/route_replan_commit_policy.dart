import '../models/trip_models.dart';

class RouteReplanCommitPolicy {
  const RouteReplanCommitPolicy._();

  static void validate({
    required TripType tripType,
    required TravelPhase travelPhase,
    required String leaderId,
    required String actorUserId,
  }) {
    final normalizedLeaderId = leaderId.trim();
    final normalizedActorUserId = actorUserId.trim();

    if (normalizedLeaderId.isEmpty) {
      throw StateError('TripのleaderIdが空です');
    }
    if (normalizedActorUserId.isEmpty) {
      throw ArgumentError.value(
        actorUserId,
        'actorUserId',
        'must not be empty',
      );
    }
    if (travelPhase != TravelPhase.active) {
      throw StateError(
        '移動中ではないTripには再探索を適用できません: phase=${travelPhase.name}',
      );
    }
    if (normalizedActorUserId != normalizedLeaderId) {
      throw StateError(
        '経路を変更できるのはリーダーだけです: '
        'actor=$normalizedActorUserId, leader=$normalizedLeaderId',
      );
    }

    switch (tripType) {
      case TripType.solo:
      case TripType.group:
        return;
    }
  }
}
