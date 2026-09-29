import 'dart:async';
import 'dart:ui';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import '../l10n/app_localizations.dart';
import '../l10n/city_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';
import '../providers/app_session_provider.dart';
import '../providers/city_profile_provider.dart';
import '../providers/delay_impact_provider.dart';
import '../providers/group_schedule_impact_provider.dart';
import '../providers/trip_provider.dart';
import '../providers/member_mode_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../widgets/active_trip_navigation_view.dart';
import '../widgets/active_trip_realtime_actions.dart';
import '../widgets/delay_recovery_card.dart';
import '../widgets/group_schedule_impact_card.dart';
import '../widgets/trip_navigation_status_card.dart';
import '../widgets/trip_schedule_window_card.dart';
import 'group_detail_page.dart';
import 'ride_stops_navigation.dart';
import 'settings_page.dart';
import 'route_detail_page.dart';

class MemberModePage extends ConsumerStatefulWidget {
  const MemberModePage({super.key});

  @override
  ConsumerState<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends ConsumerState<MemberModePage> {
  final _tripService = TripService();

  @override
  void initState() {
    super.initState();

    ref.read(memberModeControllerProvider.notifier).initialize();

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(memberNavProgressProvider.notifier).reset();
    });
  }

  @override
  Widget build(BuildContext context) {
    final uiStateAsync = ref.watch(memberUiStateProvider);
    final appName = localizedCityAppName(
      AppLocalizations.of(context),
      ref.watch(cityProfileProvider).city,
    );
    final delayResolution = ref.watch(resolvedDelayImpactProvider);
    final delayImpact = delayResolution.impact;
    final scheduleImpact = ref.watch(groupScheduleImpactProvider);
    final realtimeDiagnostic = delayResolution.nextRideRealtimeError == null
        ? null
        : AppLocalizations.of(context).realtimeScheduleFallback(
            delayResolution.nextRideRealtimeError.toString(),
          );

    return uiStateAsync.when(
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (err, stack) => Scaffold(
        appBar: CupertinoNavigationBar(middle: Text(appName)),
        body: Center(
          child: Text(
            AppLocalizations.of(context).errorWithMessage(err.toString()),
          ),
        ),
      ),
      data: (uiState) {
        final trip = ref.read(tripStreamProvider).value!;
        if (trip.status == TripStatus.cancelled ||
            trip.status == TripStatus.completed) {
          Future.microtask(() {
            if (mounted) _leaveGroup();
          });
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        final beforeScheduleSections = <Widget>[];
        if (delayImpact?.requiresReplan == true) {
          beforeScheduleSections.add(
            DelayRecoveryCard(
              impact: delayImpact!,
              nextRideRealtime: delayResolution.nextRideRealtime,
              scheduledNextDepartureAt:
                  delayResolution.scheduledNextDepartureAt,
              realtimeDiagnostic: realtimeDiagnostic,
              helperText: AppLocalizations.of(context).groupMemberReplanNotice,
            ),
          );
        }
        if (scheduleImpact != null) {
          beforeScheduleSections.add(
            GroupScheduleImpactCard(
              impact: scheduleImpact,
              helperText: AppLocalizations.of(
                context,
              ).groupMemberScheduleNotice,
            ),
          );
        }

        return ActiveTripNavigationView(
          navState: uiState.navState,
          tripTitle: uiState.displayTitle,
          appBar: _buildAppBar(context, appName, uiState.displayTitle, trip),
          onTapStops: () => openCurrentRideStops(
            context: context,
            trip: trip,
            currentStepId: ref.read(memberNavProgressProvider).currentStepId,
          ),
          statusHeaderTrailing: const _LiveClock(),
          beforeScheduleSections: beforeScheduleSections,
          scheduleSection: TripScheduleWindowCard(
            title: AppLocalizations.of(context).groupTodaySchedule,
            resolvedEntry: uiState.resolvedEntry,
            entries: uiState.windowEntries,
            completedCount: uiState.completedCount,
            activeLabel: uiState.activeLabel,
            counterLabelBuilder: (completedCount, totalCount) =>
                AppLocalizations.of(
                  context,
                ).groupCompletedCount(completedCount),
            appearance: TripScheduleWindowAppearance.boxedRows,
            activeDetail: TripNavigationInlineStatus(
              navState: uiState.navState,
              onTapStops: () => openCurrentRideStops(
                context: context,
                trip: trip,
                currentStepId: ref
                    .read(memberNavProgressProvider)
                    .currentStepId,
              ),
            ),
            emptyLabel: AppLocalizations.of(context).groupScheduleAllCompleted,
          ),
          afterScheduleSections: [
            _HelperNotice(onHelp: () => _sendSOS(trip.id)),
            const SizedBox(height: 66),
          ],
          bottomNavigationBar: _MemberActionBar(
            onHelp: () => _sendSOS(trip.id),
            onOpenDetail: () => _openGroupDetail(trip),
            onExit: _leaveGroup,
          ),
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 16,
            vertical: 12,
          ),
        );
      },
    );
  }

  Future<void> _leaveGroup() async {
    await ref.read(appSessionProvider.notifier).leaveMemberMode();
  }

  void _openGroupDetail(Trip trip) {
    Navigator.of(
      context,
      rootNavigator: true,
    ).push(CupertinoPageRoute(builder: (_) => GroupDetailPage(trip: trip)));
  }

  Future<void> _sendSOS(String tripId) async {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('SOS'),
        content: Text(AppLocalizations.of(context).groupNotifyQuestion),
        actions: [
          CupertinoDialogAction(
            child: Text(AppLocalizations.of(context).cancel),
            onPressed: () => Navigator.pop(ctx),
          ),
          CupertinoDialogAction(
            isDestructiveAction: true,
            onPressed: () async {
              Navigator.pop(ctx);
              await _tripService.sendSOS(tripId);
              if (mounted) {
                showCupertinoDialog(
                  context: context,
                  builder: (ctx2) => CupertinoAlertDialog(
                    content: Text(AppLocalizations.of(context).groupNotified),
                    actions: [
                      CupertinoDialogAction(
                        child: Text(AppLocalizations.of(context).ok),
                        onPressed: () => Navigator.pop(ctx2),
                      ),
                    ],
                  ),
                );
              }
            },
            child: Text(AppLocalizations.of(context).groupNotify),
          ),
        ],
      ),
    );
  }

  AppBar _buildAppBar(
    BuildContext context,
    String appName,
    String title,
    Trip trip,
  ) {
    return AppBar(
      backgroundColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleSpacing: 0,
      title: ActiveTripAppBarTitle(
        appName: appName,
        tripTitle: title,
        contextLabel: AppLocalizations.of(context).groupMemberMode,
      ),
      leading: IconButton(
        icon: const Icon(CupertinoIcons.doc_text, color: Colors.black87),
        onPressed: () => _openGroupDetail(trip),
      ),
      actions: [
        const ActiveTripRealtimeActions(),
        IconButton(
          icon: const Icon(Icons.settings),
          onPressed: () => Navigator.of(
            context,
          ).push(MaterialPageRoute(builder: (_) => const SettingsPage())),
        ),
        TextButton(
          onPressed: () => showCupertinoDialog(
            context: context,
            builder: (ctx) => CupertinoAlertDialog(
              title: Text(AppLocalizations.of(context).groupExitMode),
              content: Text(AppLocalizations.of(context).groupExitQuestion),
              actions: [
                CupertinoDialogAction(
                  child: Text(AppLocalizations.of(context).groupNo),
                  onPressed: () => Navigator.pop(ctx),
                ),
                CupertinoDialogAction(
                  isDestructiveAction: true,
                  onPressed: () {
                    Navigator.pop(ctx);
                    _leaveGroup();
                  },
                  child: Text(AppLocalizations.of(context).groupYes),
                ),
              ],
            ),
          ),
          child: Text(
            AppLocalizations.of(context).navTripEndedMain,
            style: TextStyle(color: CupertinoColors.destructiveRed),
          ),
        ),
      ],
    );
  }
}

class _HelperNotice extends StatelessWidget {
  final VoidCallback onHelp;
  const _HelperNotice({required this.onHelp});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFEBEE),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          const Icon(
            CupertinoIcons.exclamationmark_triangle_fill,
            color: Colors.red,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              AppLocalizations.of(context).groupHelpNotice,
              style: TextStyle(fontWeight: FontWeight.bold),
            ),
          ),
          ElevatedButton(
            onPressed: onHelp,
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.red,
              foregroundColor: Colors.white,
            ),
            child: Text(AppLocalizations.of(context).groupHelp),
          ),
        ],
      ),
    );
  }
}

class _MemberActionBar extends StatelessWidget {
  final VoidCallback onHelp;
  final VoidCallback onOpenDetail;
  final VoidCallback onExit;

  const _MemberActionBar({
    required this.onHelp,
    required this.onOpenDetail,
    required this.onExit,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: onHelp,
                    icon: const Icon(CupertinoIcons.phone),
                    label: Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        AppLocalizations.of(context).groupHelpContact,
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onOpenDetail,
                    icon: const Icon(CupertinoIcons.doc_text),
                    label: Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        AppLocalizations.of(context).groupGuideTitle,
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.black,
                      side: const BorderSide(color: Colors.black87, width: 1.2),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: TextButton(
                onPressed: onExit,
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: 10),
                  child: Text(
                    AppLocalizations.of(context).groupReturnNormal,
                    style: TextStyle(
                      color: Colors.black87,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LiveClock extends StatefulWidget {
  const _LiveClock();
  @override
  State<_LiveClock> createState() => _LiveClockState();
}

class _LiveClockState extends State<_LiveClock> {
  late final Timer _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final now = appClock.now();
    final timeStr =
        '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(CupertinoIcons.clock, size: 16, color: Colors.black54),
          const SizedBox(width: 4),
          Text(
            timeStr,
            style: const TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.w600,
              fontFeatures: [FontFeature.tabularFigures()],
              color: Colors.black87,
            ),
          ),
        ],
      ),
    );
  }
}
