import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/services/storage_service.dart';

void main() {
  test('saved route memo persists in local storage', () async {
    SharedPreferences.setMockInitialValues({});

    final candidate = Candidate(
      id: 'saved-route',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 1,
      totalTime: 1,
      steps: const [],
      points: const [],
    ).withSavedRouteMemo('朝はこの経路');

    final storage = StorageService();
    await storage.saveRoutes([candidate]);

    final restored = await storage.loadRoutes();
    expect(restored, hasLength(1));
    expect(restored.single.savedRouteMemo, '朝はこの経路');
  });
}
