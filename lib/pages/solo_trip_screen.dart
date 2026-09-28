import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

import '../logic/route_replan_presentation.dart';
import '../logic/solo_trip_lifecycle.dart';
import '../l10n/app_localizations.dart';
import '../l10n/city_localizations.dart';
import '../l10n/trip_display_localizations.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';
import '../providers/city_profile_provider.dart';
import '../providers/delay_impact_provider.dart';
import '../providers/member_mode_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../providers/trip_provider.dart';
import '../services/trip_service.dart';
import '../widgets/active_trip_navigation_view.dart';
import '../widgets/app_navigation_bar.dart';
import '../widgets/active_trip_realtime_actions.dart';
import '../widgets/delay_recovery_card.dart';
import '../widgets/route_map_preview.dart';
import '../widgets/route_replan_preview_button.dart';
import '../widgets/trip_navigation_status_card.dart';
import '../widgets/trip_schedule_window_card.dart';
import 'ride_stops_navigation.dart';
import 'solo_trip_route_page.dart';

class SoloTripScreen extends StatelessWidget {
  final String tripId;

  const SoloTripScreen({super.key, required this.tripId});

  @override
  Widget build(BuildContext context) {
    return ProviderScope(
      overrides: [
        tripStreamProvider.overrideWith(
          (ref) => TripService().streamTrip(tripId).map<Trip?>((trip) => trip),
        ),
      ],
      child: SoloTripView(tripId: tripId),
    );
  }
}

class SoloTripView extends ConsumerStatefulWidget {
  final String tripId;

  const SoloTripView({
    super.key,
    required this.tripId,
  });

  @override
  ConsumerState<SoloTripView> createState() => _SoloTripViewState();
}

class _SoloTripViewState extends ConsumerState<SoloTripView> {
  final TripService _tripService = TripService();
  bool _completionRequested = false;
  bool _completionFailed = false;
  bool _cancelling = false;
  MemberUiState? _arrivalUiSnapshot;
  String? _lastDiagnosticSignature;

  @override
  void initState() {
    super.initState();
    debugPrint('[SoloTripLifecycle] init tripId=${widget.tripId}');

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;

      ref.read(memberNavProgressProvider.notifier).reset();
      ref.read(memberModeControllerProvider.notifier).initialize();
    });
  }

  @override
  void dispose() {
    debugPrint(
      '[SoloTripLifecycle] dispose '
      'tripId=${widget.tripId} '
      'completionRequested=$_completionRequested '
      'completionFailed=$_completionFailed '
      'cancelling=$_cancelling',
    );
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final tripAsync = ref.watch(tripStreamProvider);
    final uiAsync = ref.watch(memberUiStateProvider);
    final cityProfile = ref.watch(cityProfileProvider);
    final appName = localizedCityAppName(l10n, cityProfile.city);

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.dark.copyWith(
        statusBarColor: Colors.transparent,
        systemNavigationBarColor: Colors.white,
        systemNavigationBarIconBrightness: Brightness.dark,
      ),
      child: tripAsync.when(
        loading: () =>
            const Scaffold(body: Center(child: CircularProgressIndicator())),
        error: (error, stack) => Scaffold(
          appBar: AppBar(
            systemOverlayStyle: SystemUiOverlayStyle.dark,
            title: cityBrandNavigationTitle(
              city: cityProfile.city,
              fallbackTitle: appName,
            ),
          ),
          body: Center(child: Text(l10n.tripLoadFailed(error.toString()))),
        ),
        data: (trip) {
          if (trip == null) {
            return Scaffold(body: Center(child: Text(l10n.tripNotFound)));
          }
          if (trip.travelPhase == TravelPhase.completed) {
            final arrivalUiSnapshot = _arrivalUiSnapshot;
            _logDiagnosticState(
              trip: trip,
              uiState: arrivalUiSnapshot,
              terminalArrival: true,
            );
            if (arrivalUiSnapshot != null) {
              return _buildTripScaffold(
                trip: trip,
                uiState: arrivalUiSnapshot,
                terminalArrival: true,
                completed: true,
              );
            }
            return _buildCompleted();
          }
          if (trip.travelPhase == TravelPhase.cancelled) {
            _logDiagnosticState(trip: trip);
            return _buildCancelled();
          }

          return uiAsync.when(
            loading: () => const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            ),
            error: (error, stack) => Scaffold(
              appBar: AppBar(
                systemOverlayStyle: SystemUiOverlayStyle.dark,
                title: cityBrandNavigationTitle(
                  city: cityProfile.city,
                  fallbackTitle: appName,
                ),
              ),
              body: Center(
                child: Text(l10n.navigationLoadFailed(error.toString())),
              ),
            ),
            data: (uiState) {
              final terminalArrival = shouldAutoCompleteSoloTrip(
                trip: trip,
                resolvedEntry: uiState.resolvedEntry,
              );
              _logDiagnosticState(
                trip: trip,
                uiState: uiState,
                terminalArrival: terminalArrival,
              );
              if (terminalArrival) {
                _requestAutoCompletion(trip, uiState);
              }

              return _buildTripScaffold(
                trip: trip,
                uiState: uiState,
                terminalArrival: terminalArrival,
                completed: false,
              );
            },
          );
        },
      ),
    );
  }

  Widget _buildTripScaffold({
    required Trip trip,
    required MemberUiState uiState,
    required bool terminalArrival,
    required bool completed,
  }) {
    final l10n = AppLocalizations.of(context);
    final cityProfile = ref.watch(cityProfileProvider);
    final appName = localizedCityAppName(l10n, cityProfile.city);
    final locale = Localizations.localeOf(context);
    final tripTitle = localizedSoloTripTitle(locale, trip);
    final delayResolution = ref.watch(resolvedDelayImpactProvider);
    final delayImpact = delayResolution.impact;
    final presentation = RouteReplanPresentation.fromDelayImpact(delayImpact);
    final showDelayWarning =
        !completed && !terminalArrival && presentation.showWarning;
    final showStandaloneReplan =
        !completed &&
        !terminalArrival &&
        !showDelayWarning &&
        presentation.showAction;
    final realtimeDiagnostic = delayResolution.nextRideRealtimeError == null
        ? null
        : l10n.realtimeScheduleFallback(
            delayResolution.nextRideRealtimeError.toString(),
          );
    if (!trip.isSolo || trip.legs.length != 1) {
      throw StateError(
        'SoloTripView requires a single-leg solo trip: '
        'tripId=${trip.id}, type=${trip.tripType.name}, legs=${trip.legs.length}',
      );
    }
    final routePoints = trip.legs.single.candidate.points;

    final beforeScheduleSections = <Widget>[
      if (routePoints.isNotEmpty)
        RouteMapPreview(
          key: ValueKey(Object.hashAll(routePoints)),
          points: routePoints,
          showOpenButton: false,
          height: 150,
          margin: EdgeInsets.zero,
          interactive: false,
        ),
    ];
    if (showDelayWarning) {
      beforeScheduleSections.add(
        DelayRecoveryCard(
          impact: delayImpact!,
          nextRideRealtime: delayResolution.nextRideRealtime,
          scheduledNextDepartureAt: delayResolution.scheduledNextDepartureAt,
          realtimeDiagnostic: realtimeDiagnostic,
          helperText: l10n.replanHelper,
          action: RouteReplanPreviewButton(trip: trip),
        ),
      );
    } else if (showStandaloneReplan) {
      beforeScheduleSections.add(RouteReplanPreviewButton(trip: trip));
    }

    return ActiveTripNavigationView(
      navState: uiState.navState,
      tripTitle: tripTitle,
      appBar: AppBar(
        systemOverlayStyle: SystemUiOverlayStyle.dark,
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: ActiveTripAppBarTitle(
          appName: appName,
          tripTitle: tripTitle,
          brand: cityBrandNavigationTitle(
            city: cityProfile.city,
            fallbackTitle: appName,
          ),
        ),
        actions: [
          if (!completed) const ActiveTripRealtimeActions(),
        ],
      ),
      onTapStops: () => openCurrentRideStops(
        context: context,
        trip: trip,
        currentStepId: ref.read(memberNavProgressProvider).currentStepId,
      ),
      beforeScheduleSections: beforeScheduleSections,
      scheduleSection: TripScheduleWindowCard(
        title: l10n.currentRoute,
        resolvedEntry: uiState.resolvedEntry,
        entries: uiState.windowEntries,
        completedCount: completed
            ? trip.schedule.length
            : uiState.completedCount,
        totalCount: trip.schedule.length,
        activeLabel: _localizedScheduleActiveLabel(
          uiState.activeLabel,
          l10n,
        ),
        counterLabelBuilder: (completedCount, totalCount) {
          if (totalCount == null) {
            throw StateError('Soloの予定ウィンドウにtotalCountがありません');
          }
          return l10n.stepCounter(completedCount, totalCount);
        },
        appearance: TripScheduleWindowAppearance.listTiles,
        activeDetail: TripNavigationInlineStatus(
          navState: uiState.navState,
          onTapStops: () => openCurrentRideStops(
            context: context,
            trip: trip,
            currentStepId: ref.read(memberNavProgressProvider).currentStepId,
          ),
        ),
        entryLabelBuilder: (entry) => localizedSoloScheduleEntryCompactLabel(
          locale,
          trip: trip,
          entry: entry,
        ),
        onTapEntry: (entry) {
          if (entry.itemKind != ScheduleEntryKind.ride) return;
          openRideStops(context: context, trip: trip, entry: entry);
        },
      ),
      afterScheduleSections: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => SoloTripRoutePage(tripId: trip.id),
                ),
              ),
              icon: const Icon(Icons.route),
              label: Text(l10n.viewFullRoute),
            ),
            const SizedBox(height: 8),
            if (completed)
              FilledButton(
                onPressed: () => Navigator.of(context).pop(),
                child: Text(l10n.close),
              )
            else if (terminalArrival)
              if (_completionFailed)
                TextButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: Text(l10n.close),
                )
              else
                const SizedBox.shrink()
            else
              TextButton(
                onPressed: _cancelling ? null : () => _cancelTrip(trip),
                child: Text(
                  _cancelling ? l10n.endingTrip : l10n.cancelTrip,
                ),
              ),
          ],
        ),
      ],
    );
  }

  String _localizedScheduleActiveLabel(
    String label,
    AppLocalizations l10n,
  ) {
    switch (label) {
      case 'いま':
        return l10n.scheduleNow;
      case 'つぎ':
        return l10n.scheduleNext;
      case 'そのうち':
        return l10n.scheduleLater;
      default:
        throw StateError('Unsupported solo schedule active label: $label');
    }
  }

  void _logDiagnosticState({
    required Trip trip,
    MemberUiState? uiState,
    bool? terminalArrival,
  }) {
    final navProgress = ref.read(memberNavProgressProvider);
    final bus = navProgress.busProgress;
    final rail = navProgress.railProgress;
    final entry = uiState?.resolvedEntry;
    final signature = <String>[
      'tripId=${trip.id}',
      'phase=${trip.travelPhase.name}',
      'entryId=${entry?.id ?? "-"}',
      'entryKind=${entry?.itemKind.name ?? "-"}',
      'entryLabel=${entry?.label ?? "-"}',
      'entryStep=${entry?.routeStepId ?? "-"}',
      'navStep=${navProgress.currentStepId ?? "-"}',
      'busPhase=${bus?.phase.name ?? "-"}',
      'busFrom=${bus?.fromStopId ?? "-"}',
      'busNext=${bus?.nextStopId ?? "-"}',
      'railPhase=${rail?.phase.name ?? "-"}',
      'navStatus=${uiState?.navState.statusLabel ?? "-"}',
      'terminalArrival=${terminalArrival?.toString() ?? "-"}',
      'completionRequested=$_completionRequested',
    ].join(' ');
    if (_lastDiagnosticSignature == signature) return;
    _lastDiagnosticSignature = signature;
    debugPrint('[SoloTripLifecycle] state $signature');
  }

  void _requestAutoCompletion(Trip trip, MemberUiState uiState) {
    final l10n = AppLocalizations.of(context);
    if (_completionRequested || _completionFailed) return;

    debugPrint(
      '[SoloTripLifecycle] auto-completion scheduled '
      'tripId=${trip.id} entry=${uiState.resolvedEntry?.id}',
    );
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || _completionRequested || _completionFailed) return;

      setState(() {
        _arrivalUiSnapshot = uiState;
        _completionRequested = true;
      });

      try {
        debugPrint(
          '[SoloTripLifecycle] completeTrip START tripId=${trip.id}',
        );
        await _tripService.completeTrip(trip.id);
        debugPrint(
          '[SoloTripLifecycle] completeTrip DONE tripId=${trip.id}',
        );
      } catch (error, stackTrace) {
        debugPrint(
          '[SoloTripLifecycle] completeTrip ERROR '
          'tripId=${trip.id}: $error',
        );
        debugPrintStack(stackTrace: stackTrace);
        if (!mounted) return;
        setState(() {
          _completionRequested = false;
          _completionFailed = true;
        });
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(
          SnackBar(content: Text(l10n.arrivalSaveFailed(error.toString()))),
        );
      }
    });
  }

  Future<void> _cancelTrip(Trip trip) async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l10n.cancelTripQuestion),
        content: Text(l10n.cancelTripHistoryNotice),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(l10n.back),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(l10n.cancelAction),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _cancelling = true);
    try {
      await _tripService.cancelTrip(trip.id);
    } catch (error) {
      if (mounted) {
        setState(() => _cancelling = false);
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(
          SnackBar(content: Text(l10n.cancelTripFailed(error.toString()))),
        );
      }
    }
  }

  Widget _buildCompleted() {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  l10n.arrived,
                  style: const TextStyle(
                    fontSize: 32,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 28),
                FilledButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: Text(l10n.close),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCancelled() {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      body: Center(
        child: FilledButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(l10n.close),
        ),
      ),
    );
  }
}
