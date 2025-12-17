import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../core/api_client.dart';
import '../models/explore_models.dart';

// 状態を管理するNotifierProvider
final exploreProvider =
    StateNotifierProvider<ExploreNotifier, AsyncValue<ReachableResponse?>>(
        (ref) {
  return ExploreNotifier();
});

class ExploreNotifier extends StateNotifier<AsyncValue<ReachableResponse?>> {
  ExploreNotifier() : super(const AsyncData(null));

  Future<void> search(LatLng location) async {
    state = const AsyncLoading();
    try {
      // バックエンドのAPIエンドポイントを叩く
      // ※ paramsは文字列にする必要があるため toString()
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
  
  void reset() {
    state = const AsyncData(null);
  }
}