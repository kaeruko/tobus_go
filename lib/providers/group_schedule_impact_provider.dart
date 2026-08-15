import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../logic/group_schedule_impact.dart';
import '../models/trip_models.dart';
import 'member_mode_provider.dart';
import 'minute_ticker_provider.dart';
import 'trip_provider.dart';

/// Read-only warning for group plans whose next manual event would begin before
/// the traveler can reach the current leg destination.
///
/// This provider never mutates schedule entries. It uses final-ride realtime
/// only when that estimate can be propagated to the leg goal without crossing
/// another transit service; otherwise it keeps the route-generated goal time.
final groupScheduleImpactProvider =
    Provider.autoDispose<GroupScheduleImpact?>((ref) {
      final tripAsync = ref.watch(tripStreamProvider);
      final uiAsync = ref.watch(memberUiStateProvider);
      final realtime = ref.watch(memberModeControllerProvider);
      final nowTick = ref.watch(minuteTickerProvider);

      if (!tripAsync.hasValue || !uiAsync.hasValue) return null;
      final trip = tripAsync.value;
      final uiState = uiAsync.value;
      if (trip == null || uiState == null) return null;
      if (trip.tripType != TripType.group ||
          trip.travelPhase != TravelPhase.active) {
        return null;
      }

      final now = nowTick.value ?? appClock.now();
      GroupArrivalEstimate? arrival;

      final observation = realtime.ridingTransitObservation;
      if (observation != null) {
        arrival = GroupScheduleImpactAnalyzer.estimateFromFinalRideRealtime(
          trip: trip,
          observation: observation,
        );
      }

      if (arrival == null) {
        final activeEntry = uiState.resolvedEntry;
        if (activeEntry == null) return null;
        final legIndex = activeEntry.legIndex;
        if (legIndex < 0 || legIndex >= trip.legs.length) {
          throw StateError(
            '現在予定のlegIndexがTrip範囲外です: '
            'legIndex=$legIndex, legs=${trip.legs.length}',
          );
        }
        arrival = GroupScheduleImpactAnalyzer.estimateFromRouteSchedule(
          trip: trip,
          legIndex: legIndex,
        );
      }

      return GroupScheduleImpactAnalyzer.findFirstManualConflict(
        trip: trip,
        arrival: arrival,
        now: now,
      );
    }, dependencies: [
      tripStreamProvider,
      memberUiStateProvider,
      memberModeControllerProvider,
    ]);
