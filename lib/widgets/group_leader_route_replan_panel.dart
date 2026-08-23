import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/route_replan_presentation.dart';
import '../models/trip_models.dart';
import '../providers/delay_impact_provider.dart';
import '../providers/group_schedule_impact_provider.dart';
import '../providers/member_mode_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../providers/trip_provider.dart';
import '../services/trip_service.dart';
import 'delay_recovery_card.dart';
import 'group_schedule_impact_card.dart';
import 'group_schedule_shift_button.dart';
import 'route_replan_preview_button.dart';

class GroupLeaderRouteReplanPanel extends StatelessWidget {
  final String tripId;
  final bool warningOnly;
  final bool alwaysShowAction;

  const GroupLeaderRouteReplanPanel({
    super.key,
    required this.tripId,
    this.warningOnly = false,
    this.alwaysShowAction = false,
  });

  @override
  Widget build(BuildContext context) {
    final normalizedTripId = tripId.trim();
    if (normalizedTripId.isEmpty) {
      throw ArgumentError.value(tripId, 'tripId', 'must not be empty');
    }

    return ProviderScope(
      overrides: [
        tripStreamProvider.overrideWith(
          (ref) => TripService()
              .streamTrip(normalizedTripId)
              .map<Trip?>((trip) => trip),
        ),
        memberNavProgressProvider.overrideWith(
          (ref) => MemberNavProgressNotifier(),
        ),
      ],
      child: _GroupLeaderRouteReplanPanelBody(
        warningOnly: warningOnly,
        alwaysShowAction: alwaysShowAction,
      ),
    );
  }
}

class _GroupLeaderRouteReplanPanelBody extends ConsumerStatefulWidget {
  final bool warningOnly;
  final bool alwaysShowAction;

  const _GroupLeaderRouteReplanPanelBody({
    required this.warningOnly,
    required this.alwaysShowAction,
  });

  @override
  ConsumerState<_GroupLeaderRouteReplanPanelBody> createState() =>
      _GroupLeaderRouteReplanPanelBodyState();
}

class _GroupLeaderRouteReplanPanelBodyState
    extends ConsumerState<_GroupLeaderRouteReplanPanelBody> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      ref.read(memberNavProgressProvider.notifier).reset();
      ref.read(memberModeControllerProvider.notifier).initialize();
    });
  }

  @override
  Widget build(BuildContext context) {
    return GroupLeaderRouteReplanContent(
      warningOnly: widget.warningOnly,
      alwaysShowAction: widget.alwaysShowAction,
    );
  }
}

/// Group leader向けの経路見直し・手動予定調整部分。
///
/// ProviderScopeやRealtime pollingの初期化は所有しないため、
/// `ActiveTripNavigationView` と同じProviderScopeの中へそのまま配置できる。
/// 単体利用が必要な既存画面は [GroupLeaderRouteReplanPanel] がScopeを用意する。
class GroupLeaderRouteReplanContent extends ConsumerWidget {
  final bool warningOnly;
  final bool alwaysShowAction;

  const GroupLeaderRouteReplanContent({
    super.key,
    this.warningOnly = false,
    this.alwaysShowAction = false,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tripAsync = ref.watch(tripStreamProvider);
    final delayResolution = ref.watch(resolvedDelayImpactProvider);
    final delayImpact = delayResolution.impact;
    final presentation = RouteReplanPresentation.fromDelayImpact(delayImpact);
    final scheduleImpact = ref.watch(groupScheduleImpactProvider);
    final realtimeDiagnostic = delayResolution.nextRideRealtimeError == null
        ? null
        : '次便のRealtime確認に失敗したため、予定時刻で判定しています: '
            '${delayResolution.nextRideRealtimeError}';

    return tripAsync.when(
      loading: () => alwaysShowAction && !warningOnly
          ? const Padding(
              padding: EdgeInsets.symmetric(vertical: 20),
              child: Center(child: CircularProgressIndicator()),
            )
          : const SizedBox.shrink(),
      error: (error, stack) => warningOnly
          ? const SizedBox.shrink()
          : Card(
              elevation: 0,
              color: Colors.red.shade50,
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Text('経路見直しを準備できませんでした: $error'),
              ),
            ),
      data: (trip) {
        if (trip == null ||
            trip.tripType != TripType.group ||
            trip.travelPhase != TravelPhase.active) {
          if (alwaysShowAction && !warningOnly) {
            return Card(
              elevation: 0,
              color: Colors.grey.shade100,
              child: const Padding(
                padding: EdgeInsets.all(14),
                child: Text('おでかけの開始状態を確認しています…'),
              ),
            );
          }
          return const SizedBox.shrink();
        }

        final replanButton = RouteReplanPreviewButton(
          trip: trip,
          allowGroupLeaderApply: true,
        );
        final warnings = <Widget>[];

        if (presentation.showWarning) {
          warnings.add(
            DelayRecoveryCard(
              impact: delayImpact!,
              nextRideRealtime: delayResolution.nextRideRealtime,
              scheduledNextDepartureAt:
                  delayResolution.scheduledNextDepartureAt,
              realtimeDiagnostic: realtimeDiagnostic,
              helperText:
                  'この変更はリーダーだけが確定できます。確定後は参加者の画面にも反映されます。',
              action: replanButton,
            ),
          );
        }

        if (scheduleImpact != null) {
          if (warnings.isNotEmpty) {
            warnings.add(const SizedBox(height: 10));
          }
          warnings.add(
            GroupScheduleImpactCard(
              impact: scheduleImpact,
              helperText:
                  '休憩などの手動予定だけを調整できます。交通便と帰りの経路は自動では動かしません。',
              action: GroupScheduleShiftButton(
                trip: trip,
                impact: scheduleImpact,
              ),
            ),
          );
        }

        if (warningOnly) {
          if (warnings.isEmpty) return const SizedBox.shrink();
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: warnings,
          );
        }

        if (presentation.showWarning) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: warnings,
          );
        }

        if (!presentation.showAction && !alwaysShowAction) {
          if (warnings.isEmpty) return const SizedBox.shrink();
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: warnings,
          );
        }

        final defaultReplanCard = _DefaultGroupReplanCard(
          replanButton: replanButton,
        );

        if (warnings.isNotEmpty) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ...warnings,
              const SizedBox(height: 10),
              defaultReplanCard,
            ],
          );
        }

        return defaultReplanCard;
      },
    );
  }
}

class _DefaultGroupReplanCard extends StatelessWidget {
  final Widget replanButton;

  const _DefaultGroupReplanCard({required this.replanButton});

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      color: Colors.blue.shade50,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.blue.shade100),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.alt_route, color: Colors.blue.shade700),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    '移動中の経路を調整',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            const Text(
              '駅・停留所の進捗から再検索します。変更すると参加者の画面にも反映されます。',
              style: TextStyle(fontSize: 13, color: Colors.black54),
            ),
            replanButton,
          ],
        ),
      ),
    );
  }
}
