import 'package:google_maps_flutter/google_maps_flutter.dart';

enum ReplanAnchorSource {
  tripOrigin,
  lastConfirmedTransitPlace,
  currentTransitPlace,
  predictedNextTransitPlace,
}

enum RidingTransitMotion {
  stopped,
  inTransit,
}

class ReplanTransitPlace {
  final String name;
  final String? stopId;
  final LatLng point;

  ReplanTransitPlace({
    required String name,
    this.stopId,
    required this.point,
  }) : name = name.trim() {
    if (this.name.isEmpty) {
      throw ArgumentError.value(name, 'name', 'must not be empty');
    }
    if (!point.latitude.isFinite || !point.longitude.isFinite) {
      throw ArgumentError.value(point, 'point', 'must be finite');
    }
  }
}

/// A normalized observation for a transit vehicle the user is already riding.
///
/// This intentionally does not know about GPS. Bus/train-specific realtime
/// models must be converted into this shape before resolving a replan anchor.
class RidingTransitObservation {
  final String stepId;
  final RidingTransitMotion motion;
  final ReplanTransitPlace? currentPlace;
  final ReplanTransitPlace? nextPlace;
  final DateTime? predictedNextAvailableAt;

  /// Conservative realtime estimate for reaching the planned alighting point
  /// of this ride. DelayImpactAnalyzer requires this when a later transfer
  /// exists; it is never synthesized from GPS or from the device clock alone.
  final DateTime? predictedDestinationAvailableAt;

  RidingTransitObservation({
    required String stepId,
    required this.motion,
    this.currentPlace,
    this.nextPlace,
    this.predictedNextAvailableAt,
    this.predictedDestinationAvailableAt,
  }) : stepId = stepId.trim() {
    if (this.stepId.isEmpty) {
      throw ArgumentError.value(stepId, 'stepId', 'must not be empty');
    }

    switch (motion) {
      case RidingTransitMotion.stopped:
        if (currentPlace == null) {
          throw ArgumentError(
            'stopped transit observation requires currentPlace',
          );
        }
        if (predictedNextAvailableAt != null) {
          throw ArgumentError(
            'stopped transit observation must not contain predictedNextAvailableAt',
          );
        }
        break;
      case RidingTransitMotion.inTransit:
        if (nextPlace == null) {
          throw ArgumentError(
            'inTransit observation requires nextPlace',
          );
        }
        if (predictedNextAvailableAt == null) {
          throw ArgumentError(
            'inTransit observation requires predictedNextAvailableAt',
          );
        }
        break;
    }
  }
}

class ReplanAnchor {
  final String placeName;
  final String? stopId;
  final LatLng point;
  final DateTime availableAt;
  final ReplanAnchorSource source;
  final String? routeStepId;

  const ReplanAnchor({
    required this.placeName,
    required this.stopId,
    required this.point,
    required this.availableAt,
    required this.source,
    this.routeStepId,
  });
}

class ReplanAnchorContext {
  /// Non-null only while the user is already on a bus/train.
  final RidingTransitObservation? ridingTransit;

  /// The most recent station/bus stop the user is known to have reached.
  /// Used while walking after alighting or during a transfer walk.
  final ReplanTransitPlace? lastConfirmedTransitPlace;

  /// Original trip origin. Used only before the first transit place exists.
  final ReplanTransitPlace? tripOrigin;

  /// True only for the initial walk before any station/bus stop has been
  /// confirmed for this trip.
  final bool isInitialPreboardingWalk;

  const ReplanAnchorContext({
    this.ridingTransit,
    this.lastConfirmedTransitPlace,
    this.tripOrigin,
    this.isInitialPreboardingWalk = false,
  });
}

class ReplanAnchorResolver {
  const ReplanAnchorResolver._();

  static ReplanAnchor resolve({
    required ReplanAnchorContext context,
    required DateTime now,
  }) {
    final ridingTransit = context.ridingTransit;
    if (ridingTransit != null) {
      switch (ridingTransit.motion) {
        case RidingTransitMotion.stopped:
          final place = ridingTransit.currentPlace!;
          return _anchor(
            place: place,
            availableAt: now,
            source: ReplanAnchorSource.currentTransitPlace,
            routeStepId: ridingTransit.stepId,
          );
        case RidingTransitMotion.inTransit:
          final availableAt = ridingTransit.predictedNextAvailableAt!;
          if (availableAt.isBefore(now)) {
            throw StateError(
              '次停車地点の到着見込みが現在時刻より前です: '
              'now=${now.toIso8601String()}, '
              'predicted=${availableAt.toIso8601String()}, '
              'stepId=${ridingTransit.stepId}',
            );
          }
          return _anchor(
            place: ridingTransit.nextPlace!,
            availableAt: availableAt,
            source: ReplanAnchorSource.predictedNextTransitPlace,
            routeStepId: ridingTransit.stepId,
          );
      }
    }

    final lastConfirmed = context.lastConfirmedTransitPlace;
    if (lastConfirmed != null) {
      return _anchor(
        place: lastConfirmed,
        availableAt: now,
        source: ReplanAnchorSource.lastConfirmedTransitPlace,
      );
    }

    if (context.isInitialPreboardingWalk) {
      final origin = context.tripOrigin;
      if (origin == null) {
        throw StateError('最初の乗車前徒歩ですが、経路の出発地点がありません');
      }
      return _anchor(
        place: origin,
        availableAt: now,
        source: ReplanAnchorSource.tripOrigin,
      );
    }

    throw StateError(
      '再探索起点を確定できません。GPSへのフォールバックは行いません。',
    );
  }

  static ReplanAnchor _anchor({
    required ReplanTransitPlace place,
    required DateTime availableAt,
    required ReplanAnchorSource source,
    String? routeStepId,
  }) {
    return ReplanAnchor(
      placeName: place.name,
      stopId: place.stopId,
      point: place.point,
      availableAt: availableAt,
      source: source,
      routeStepId: routeStepId,
    );
  }
}
