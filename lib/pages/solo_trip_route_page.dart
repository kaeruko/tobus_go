import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/city_profile.dart';
import '../l10n/app_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../models/trip_models.dart';
import '../providers/city_profile_provider.dart';
import '../providers/trip_provider.dart';
import '../widgets/app_navigation_bar.dart';
import '../widgets/route_detail_widgets.dart';
import '../widgets/route_map_preview.dart';

/// Read-only route overview. Navigation progress/lifecycle remains owned by
/// SoloTripView underneath this route; opening or closing it never starts a trip.
class SoloTripRoutePage extends ConsumerWidget {
  final String tripId;

  const SoloTripRoutePage({super.key, required this.tripId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final city = ref.watch(cityProfileProvider).city;
    final tripAsync = ref.watch(tripRouteProvider(tripId));

    return tripAsync.when(
      skipLoadingOnRefresh: false,
      skipLoadingOnReload: false,
      data: (trip) {
        if (trip.id != tripId || !trip.isSolo || trip.legs.length != 1) {
          throw StateError(
            'Solo route overview requires the requested single-leg solo trip: '
            'requested=$tripId, actual=${trip.id}, '
            'type=${trip.tripType}, legs=${trip.legs.length}',
          );
        }
        final leg = trip.legs.single;
        final candidate = leg.candidate;
        return CupertinoPageScaffold(
          navigationBar: buildAppNavigationBar(
            middle: Text(localizedCandidateLines(locale, candidate).join(' → ')),
          ),
          child: SafeArea(
            child: CustomScrollView(
              slivers: [
                const SliverToBoxAdapter(child: SizedBox(height: 8)),
                SliverToBoxAdapter(
                  child: RouteEndpointSummary(candidate: candidate),
                ),
                SliverToBoxAdapter(child: RouteSummary(candidate: candidate)),
                const SliverToBoxAdapter(child: SizedBox(height: 12)),
                if (leg.routeGeometryIsApproximate && candidate.points.isNotEmpty)
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                      child: Text(l10n.routeGeometryApproximate),
                    ),
                  ),
                SliverToBoxAdapter(
                  child: RouteMapPreview(
                    // Recreate the map camera when a replan changes geometry.
                    key: ValueKey(Object.hashAll(candidate.points)),
                    points: candidate.points,
                  ),
                ),
                const SliverToBoxAdapter(child: SizedBox(height: 12)),
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                  sliver: SliverList(
                    delegate: SliverChildBuilderDelegate(
                      (context, index) => index.isOdd
                          ? const SizedBox(height: 8)
                          : RouteStepTile(
                              segment: candidate.steps[index ~/ 2],
                              showTimetable: city == AppCity.tokyo,
                            ),
                      childCount: candidate.steps.isEmpty
                          ? 0
                          : candidate.steps.length * 2 - 1,
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
      loading: () => CupertinoPageScaffold(
        navigationBar: buildAppNavigationBar(middle: Text(l10n.viewFullRoute)),
        child: const Center(child: CupertinoActivityIndicator()),
      ),
      error: (error, stackTrace) => CupertinoPageScaffold(
        navigationBar: buildAppNavigationBar(middle: Text(l10n.viewFullRoute)),
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: SelectableText('tripId=$tripId\n$error'),
          ),
        ),
      ),
    );
  }
}
