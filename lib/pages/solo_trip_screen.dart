import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

import '../logic/route_replan_presentation.dart';
import '../logic/solo_trip_lifecycle.dart';
import '../l10n/app_localizations.dart';
import '../l10n/city_localizations.dart';
import '../l10n/trip_display_localizations.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../providers/city_profile_provider.dart';
import '../providers/delay_impact_provider.dart';
import '../providers/member_mode_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../providers/saved_routes_provider.dart';
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

class _EndpointText {
  final String japanese;
  final String? english;

  const _EndpointText({
    required this.japanese,
    this.english,
  });
}

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
    final candidate = trip.legs.single.candidate;
    final routePoints = candidate.points;
    final isFavorite = ref
        .watch(savedRoutesProvider)
        .any((saved) => _isSameRoute(saved, candidate));

    final originEndpoint = _originEndpoint(trip);
    final destinationEndpoint = _destinationEndpoint(trip);
    final beforeScheduleSections = <Widget>[
      ActiveTripEndpointCard(
        originLabel: locale.languageCode == 'en' ? 'Origin' : '出発地',
        originPlace: _localizedEndpoint(locale, originEndpoint),
        destinationLabel:
            locale.languageCode == 'en' ? 'Destination' : '目的地',
        destinationPlace: _localizedEndpoint(locale, destinationEndpoint),
      ),
      TripNavigationStatusCard(
        navState: uiState.navState,
        tripTitle: tripTitle,
        onTapStops: () => openCurrentRideStops(
          context: context,
          trip: trip,
          currentStepId: ref.read(memberNavProgressProvider).currentStepId,
        ),
      ),
      if (routePoints.isNotEmpty)
        RouteMapPreview(
          key: ValueKey(Object.hashAll(routePoints)),
          points: routePoints,
          showOpenButton: false,
          height: 150,
          margin: EdgeInsets.zero,
          interactive: true,
          openExternalOnTap: false,
          rotateGesturesEnabled: false,
          tiltGesturesEnabled: false,
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
        title: cityBrandNavigationTitle(
          city: cityProfile.city,
          fallbackTitle: appName,
        ),
        actions: [
          if (cityProfile.capabilities.features.savedRoutes)
            IconButton(
              tooltip: isFavorite
                  ? l10n.removeFromMyRoute
                  : l10n.addToMyRoute,
              icon: Icon(
                isFavorite
                    ? CupertinoIcons.bookmark_fill
                    : CupertinoIcons.bookmark,
              ),
              onPressed: () => _toggleFavorite(candidate, isFavorite),
            ),
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

  bool _isSameRoute(Candidate a, Candidate b) {
    if (a.id != b.id) return false;
    if (a.points.isEmpty || b.points.isEmpty) return false;
    final sameStart =
        a.points.first.latitude == b.points.first.latitude &&
        a.points.first.longitude == b.points.first.longitude;
    final sameEnd =
        a.points.last.latitude == b.points.last.latitude &&
        a.points.last.longitude == b.points.last.longitude;
    return sameStart && sameEnd;
  }

  Future<void> _toggleFavorite(Candidate candidate, bool isFavorite) async {
    final l10n = AppLocalizations.of(context);

    if (!isFavorite) {
      await ref.read(savedRoutesProvider.notifier).add(candidate);
      if (!mounted) return;
      await showCupertinoDialog<void>(
        context: context,
        builder: (dialogContext) => CupertinoAlertDialog(
          title: Text(l10n.savedTitle),
          content: Text(l10n.savedToMyRoute),
          actions: [
            CupertinoDialogAction(
              onPressed: () => Navigator.pop(dialogContext),
              child: Text(l10n.ok),
            ),
          ],
        ),
      );
      return;
    }

    final confirmed = await showCupertinoDialog<bool>(
      context: context,
      builder: (dialogContext) => CupertinoAlertDialog(
        title: Text(l10n.deleteBookmarkTitle),
        content: Text(l10n.deleteBookmarkMessage),
        actions: [
          CupertinoDialogAction(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(l10n.cancel),
          ),
          CupertinoDialogAction(
            isDestructiveAction: true,
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(l10n.delete),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    await ref
        .read(savedRoutesProvider.notifier)
        .removeWhere((saved) => _isSameRoute(saved, candidate));
  }

  _EndpointText _originEndpoint(Trip trip) {
    final candidate = trip.legs.single.candidate;
    final originName = candidate.originName?.trim();
    if (originName != null && originName.isNotEmpty) {
      return _EndpointText(
        japanese: originName,
        english: candidate.originNameEn,
      );
    }

    if (candidate.steps.isEmpty) {
      throw StateError(
        'Solo移動中ヘッダーの出発地を特定できません: '
        'tripId=${trip.id}, candidateId=${candidate.id}',
      );
    }

    final first = candidate.steps.first;
    final fromName = first.fromName?.trim();
    if (fromName == null || fromName.isEmpty) {
      throw StateError(
        'Solo移動中ヘッダーの出発地を特定できません: '
        'tripId=${trip.id}, candidateId=${candidate.id}, '
        'firstStepId=${first.stepId}',
      );
    }
    return _EndpointText(
      japanese: fromName,
      english: first.fromNameEn,
    );
  }

  _EndpointText _destinationEndpoint(Trip trip) {
    final candidate = trip.legs.single.candidate;
    final destinationName = candidate.destinationName?.trim();
    if (destinationName != null && destinationName.isNotEmpty) {
      return _EndpointText(
        japanese: destinationName,
        english: candidate.destinationNameEn,
      );
    }

    if (candidate.steps.isEmpty) {
      throw StateError(
        'Solo移動中ヘッダーの目的地を特定できません: '
        'tripId=${trip.id}, candidateId=${candidate.id}',
      );
    }

    final last = candidate.steps.last;
    final toName = last.toName?.trim();
    if (toName == null || toName.isEmpty) {
      throw StateError(
        'Solo移動中ヘッダーの目的地を特定できません: '
        'tripId=${trip.id}, candidateId=${candidate.id}, '
        'lastStepId=${last.stepId}',
      );
    }
    return _EndpointText(
      japanese: toName,
      english: last.toNameEn,
    );
  }

  String _localizedEndpoint(Locale locale, _EndpointText endpoint) {
    final japanese = endpoint.japanese.trim();
    if (japanese.isEmpty) {
      throw StateError('Solo移動中ヘッダーの日本語地点名が空です');
    }
    if (locale.languageCode != 'en') return japanese;

    final english = endpoint.english?.trim();
    if (english == null || english.isEmpty || english == japanese) {
      return japanese;
    }
    return '$english ($japanese)';
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
