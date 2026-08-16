import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'replan_anchor.dart';
import 'replan_transit_memory.dart';

/// Structured, grep-friendly diagnostics for realtime route replanning.
///
/// Logs are emitted only in debug builds and intentionally contain route facts
/// rather than user GPS. Keep each event on one line so device and API logs can
/// be compared by timestamp.
class ReplanDebugLog {
  const ReplanDebugLog._();

  static void emit(String event, [Map<String, Object?> fields = const {}]) {
    if (!kDebugMode) return;
    final payload = <String, Object?>{
      'event': event,
      ...fields,
    };
    debugPrint('[ReplanTrace] ${jsonEncode(payload)}');
  }

  static Map<String, Object?> memoryFields(ReplanTransitMemory? memory) {
    final riding = memory?.ridingTransit;
    return <String, Object?>{
      'knownOnboardStepId': memory?.knownOnboardStepId,
      'lastConfirmedPlace': memory?.lastConfirmedTransitPlace?.name,
      'lastConfirmedStopId': memory?.lastConfirmedTransitPlace?.stopId,
      'ridingStepId': riding?.stepId,
      'ridingMotion': riding?.motion.name,
      'ridingCurrentPlace': riding?.currentPlace?.name,
      'ridingNextPlace': riding?.nextPlace?.name,
      'predictedNextAt': riding?.predictedNextAvailableAt?.toIso8601String(),
      'predictedDestinationAt':
          riding?.predictedDestinationAvailableAt?.toIso8601String(),
    };
  }

  static Map<String, Object?> anchorFields(ReplanAnchor? anchor) {
    return <String, Object?>{
      'anchorPlace': anchor?.placeName,
      'anchorStopId': anchor?.stopId,
      'anchorSource': anchor?.source.name,
      'anchorStepId': anchor?.routeStepId,
      'anchorAvailableAt': anchor?.availableAt.toIso8601String(),
      'anchorLat': anchor?.point.latitude,
      'anchorLng': anchor?.point.longitude,
    };
  }
}
