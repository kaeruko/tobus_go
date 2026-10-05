import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../l10n/app_localizations.dart';
import '../l10n/city_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/route_replan_presentation.dart';
import '../models/route_models.dart';
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
import '../widgets/app_navigation_bar.dart';
import '../widgets/active_trip_realtime_actions.dart';
import '../widgets/delay_recovery_card.dart';
import '../widgets/group_schedule_impact_card.dart';
import '../widgets/trip_schedule_window_card.dart';
import 'group_detail_page.dart';
import 'ride_stops_navigation.dart';
import 'settings_page.dart';

class MemberModePreviewPage extends StatelessWidget {
  final String tripId;

  const MemberModePreviewPage({super.key, required this.tripId});

  @override
  Widget build(BuildContext context) {
    return ProviderScope(
      overrides: [
        tripStreamProvider.overrideWith(
          (ref) => TripService().streamTrip(tripId).map<Trip?>((trip) => trip),
        ),
      ],
      child: const MemberModePage(previewAsLeader: true),
    );
  }
}

class MemberModePage extends ConsumerStatefulWidget {
  final bool previewAsLeader;

  const MemberModePage({super.key, this.previewAsLeader = false});

  @override
  ConsumerState<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends ConsumerState<MemberModePage> {
  final _tripService = TripService();

  @override
  Widget build(BuildContext context) {
    final uiStateAsync = ref.watch(memberUiStateProvider);
    final city = ref.watch(cityProfileProvider).city;
    final appName = localizedCityAppName(
      AppLocalizations.of(context),
      city,
    );
    final appBrand = cityBrandNavigationTitle(
      city: city,
      fallbackTitle: appName,
    );
    final delayResolution = ref.watch(resolvedDelayImpactProvider);
    final delayImpact = delayResolution.impact;
    final delayPresentation = RouteReplanPresentation.fromDelayImpact(
      delayImpact,
      nextRideRealtime: delayResolution.nextRideRealtime,
    );
    final scheduleImpact = ref.watch(groupScheduleImpactProvider);

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.dark.copyWith(
        statusBarColor: Colors.transparent,
        systemNavigationBarColor: Colors.white,
        systemNavigationBarIconBrightness: Brightness.dark,
      ),
      child: uiStateAsync.when(
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (err, stack) => Scaffold(
        appBar: CupertinoNavigationBar(middle: appBrand),
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

        final activeLeg = resolveGroupActiveLeg(trip);
        final activeCandidate = activeLeg.candidate;
        final beforeScheduleSections = <Widget>[
          ActiveTripRouteOverview(
            navState: uiState.navState,
            tripTitle: uiState.displayTitle,
            originLabel: AppLocalizations.of(context).originFallback,
            originPlace: _localizedCandidateEndpoint(
              activeCandidate,
              origin: true,
            ),
            destinationLabel: AppLocalizations.of(context).destinationFallback,
            destinationPlace: _localizedCandidateEndpoint(
              activeCandidate,
              origin: false,
            ),
            routePoints: activeCandidate.points,
            statusHeaderTrailing: _MemberTripLabel(
              title: uiState.displayTitle,
            ),
            onTapStops: () => openCurrentRideStops(
              context: context,
              trip: trip,
              currentStepId: ref.read(memberNavProgressProvider).currentStepId,
            ),
          ),
        ];
        if (delayPresentation.showWarning) {
          beforeScheduleSections.add(
            DelayRecoveryCard(
              impact: delayImpact!,
              nextRideRealtime: delayResolution.nextRideRealtime,
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
          appBar: _buildAppBar(context, appBrand, trip),
          onTapStops: () => openCurrentRideStops(
            context: context,
            trip: trip,
            currentStepId: ref.read(memberNavProgressProvider).currentStepId,
          ),
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
            exitLabel: widget.previewAsLeader
                ? AppLocalizations.of(context).groupBackToLeader
                : null,
          ),
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 16,
            vertical: 12,
          ),
        );
      },
    ),
    );
  }

  String _localizedCandidateEndpoint(
    Candidate candidate, {
    required bool origin,
  }) {
    final japanese = origin
        ? candidate.originName?.trim()
        : candidate.destinationName?.trim();
    if (japanese == null || japanese.isEmpty) {
      throw StateError(
        'Groupのactive legに地点名がありません: '
        'candidateId=${candidate.id}, endpoint=${origin ? "origin" : "destination"}',
      );
    }

    return localizedOptionalPlaceName(
      Localizations.localeOf(context),
      japanese: japanese,
      english: origin ? candidate.originNameEn : candidate.destinationNameEn,
      field: origin ? 'origin_name_en' : 'destination_name_en',
      identity: 'candidateId=${candidate.id}',
    );
  }

  Future<void> _leaveGroup() async {
    if (widget.previewAsLeader) {
      if (mounted) Navigator.of(context).pop();
      return;
    }
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
    Widget appBrand,
    Trip trip,
  ) {
    return AppBar(
      systemOverlayStyle: SystemUiOverlayStyle.dark.copyWith(
        statusBarColor: Colors.transparent,
      ),
      backgroundColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleSpacing: 0,
      title: appBrand,
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
        if (widget.previewAsLeader)
          TextButton(
            onPressed: _leaveGroup,
            child: Text(
              AppLocalizations.of(context).groupBackToLeader,
              style: const TextStyle(color: Colors.black87),
            ),
          )
        else
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
  final String? exitLabel;

  const _MemberActionBar({
    required this.onHelp,
    required this.onOpenDetail,
    required this.onExit,
    this.exitLabel,
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
                        AppLocalizations.of(context).groupGuideButton,
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
                    exitLabel ??
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


class _MemberTripLabel extends StatelessWidget {
  final String title;

  const _MemberTripLabel({required this.title});

  @override
  Widget build(BuildContext context) {
    final normalizedTitle = title.trim();
    if (normalizedTitle.isEmpty) {
      throw StateError('参加者ナビのおでかけ名が空です');
    }

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text(
          '👥',
          semanticsLabel: '参加者',
          style: TextStyle(fontSize: 14),
        ),
        const SizedBox(width: 4),
        Flexible(
          child: Text(
            normalizedTitle,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.right,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      ],
    );
  }
}
