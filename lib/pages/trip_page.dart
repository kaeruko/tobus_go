import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
    final tripAsync = ref.watch(tripStreamProvider);

    return tripAsync.when(
      loading: () => const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      ),
      error: (error, stack) => Scaffold(
        appBar: AppBar(title: const Text('移動')),
        body: Center(
          child: Text('移動を読み込めませんでした: $error'),
        ),
      ),
      data: (trip) {
        if (trip == null) {
          return const Scaffold(
            body: Center(
              child: Text('移動が見つかりません'),
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