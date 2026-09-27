import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../models/trip_models.dart';
import '../providers/trip_provider.dart';
import '../services/trip_service.dart';
import 'group_detail_page.dart';
import 'solo_trip_screen.dart';

class TripPage extends StatelessWidget {
  final String tripId;

  const TripPage({
    super.key,
    required this.tripId,
  });

  @override
  Widget build(BuildContext context) {
    return ProviderScope(
      overrides: [
        tripStreamProvider.overrideWith(
          (ref) => TripService()
              .streamTrip(tripId)
              .map<Trip?>((trip) => trip),
        ),
      ],
      child: const _TripPageBody(),
    );
  }
}

class _TripPageBody extends ConsumerWidget {
  const _TripPageBody();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final tripAsync = ref.watch(tripStreamProvider);

    return tripAsync.when(
      loading: () => const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      ),
      error: (error, stack) => Scaffold(
        appBar: AppBar(title: Text(l10n.tripTitle)),
        body: Center(
          child: Text(l10n.tripLoadFailed(error.toString())),
        ),
      ),
      data: (trip) {
        if (trip == null) {
          return Scaffold(
            body: Center(
              child: Text(l10n.tripNotFound),
            ),
          );
        }

        if (trip.isSolo) {
          return SoloTripView(tripId: trip.id);
        }

        return GroupDetailPage(trip: trip);
      },
    );
  }
}