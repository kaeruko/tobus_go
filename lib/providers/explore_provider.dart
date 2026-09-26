import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../core/api_client.dart';
import '../models/explore_models.dart';

final exploreProvider =
    StateNotifierProvider<ExploreNotifier, AsyncValue<ReachableResponse?>>(
        (ref) {
  return ExploreNotifier();
});

final exploreEditorialContentProvider =
    FutureProvider<ExploreEditorialContent>((ref) async {
  final json = await ApiClient.get('/explore/content');
  return ExploreEditorialContent.fromJson(json);
});

class ExploreNotifier extends StateNotifier<AsyncValue<ReachableResponse?>> {
  ExploreNotifier() : super(const AsyncData(null));

  Future<void> search(LatLng location) async {
    state = const AsyncLoading();
    try {
      final json = await ApiClient.get(
        '/explore/reachable',
        params: {
          'lat': location.latitude.toString(),
          'lon': location.longitude.toString(),
        },
      );

      final response = ReachableResponse.fromJson(json);
      state = AsyncData(response);
    } catch (e, st) {
      state = AsyncError(e, st);
    }
  }

  Future<ExperienceResponse> fetchExperiences(ReachableStop stop) async {
    final json = await ApiClient.post(
      '/route/experience',
      body: [
        {
          "stop_id": stop.id,
          "stop_name": stop.name,
          "lat": stop.lat,
          "lon": stop.lon,
        }
      ],
    );
    return ExperienceResponse.fromJson(json);
  }

  void reset() {
    state = const AsyncData(null);
  }
}
