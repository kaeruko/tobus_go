import '../models/leg_models.dart';
import '../models/trip_models.dart';
import 'replan_anchor.dart';
import 'replan_transit_memory.dart';

/// Builds the transport-only facts required by [ReplanAnchorResolver].
///
/// This layer deliberately does not know about user GPS. It also keeps the
/// previous leg's transit memory out of a new leg's initial preboarding phase:
/// before the first realtime ride observation of that leg exists, the leg's
/// saved route origin is the only agreed non-GPS anchor.
class ReplanAnchorContextBuilder {
  const ReplanAnchorContextBuilder._();

  static ReplanAnchorContext build({
    required Trip trip,
    required String activeStepId,
    required ReplanTransitMemory memory,
  }) {
    final stepId = activeStepId.trim();
    if (stepId.isEmpty) {
      throw ArgumentError.value(
        activeStepId,
        'activeStepId',
        'must not be empty',
      );
    }

    final position = _findStepPosition(trip, stepId);
    final steps = position.leg.candidate.steps;
    final activeStep = steps[position.stepIndex];
    final firstRideIndex = steps.indexWhere((step) => step.isRide);
    final isBeforeOrAtFirstRide =
        firstRideIndex < 0 || position.stepIndex <= firstRideIndex;

    // No transit place in the current leg has been confirmed yet. Do not reuse
    // the previous leg's station/bus stop just because it remains in memory.
    if (isBeforeOrAtFirstRide && memory.ridingTransit == null) {
      return ReplanAnchorContext(
        tripOrigin: _requiredLegOrigin(position.leg),
        isInitialPreboardingWalk: true,
      );
    }

    RidingTransitObservation? ridingTransit;
    final rememberedRide = memory.ridingTransit;
    if (activeStep.isRide && rememberedRide != null) {
      if (rememberedRide.stepId != activeStep.stepId) {
        throw StateError(
          '再探索用の乗車観測が現在stepと一致しません: '
          '${rememberedRide.stepId} != ${activeStep.stepId}',
        );
      }
      ridingTransit = rememberedRide;
    }

    return ReplanAnchorContext(
      ridingTransit: ridingTransit,
      lastConfirmedTransitPlace: memory.lastConfirmedTransitPlace,
    );
  }

  static _LegStepPosition _findStepPosition(Trip trip, String stepId) {
    final matches = <_LegStepPosition>[];
    for (final leg in trip.legs) {
      for (var index = 0; index < leg.candidate.steps.length; index++) {
        if (leg.candidate.steps[index].stepId == stepId) {
          matches.add(_LegStepPosition(leg: leg, stepIndex: index));
        }
      }
    }

    if (matches.length != 1) {
      throw StateError(
        'activeStepIdをTrip内で一意に特定できません: '
        'stepId=$stepId, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static ReplanTransitPlace _requiredLegOrigin(Leg leg) {
    final name = leg.candidate.originName?.trim();
    final point = leg.candidate.originCoords;
    if (name == null || name.isEmpty) {
      throw StateError(
        '再探索に使う経路出発地点名がありません: candidate=${leg.candidate.id}',
      );
    }
    if (point == null) {
      throw StateError(
        '再探索に使う経路出発地点座標がありません: candidate=${leg.candidate.id}',
      );
    }
    return ReplanTransitPlace(name: name, point: point);
  }
}

class _LegStepPosition {
  final Leg leg;
  final int stepIndex;

  const _LegStepPosition({required this.leg, required this.stepIndex});
}
