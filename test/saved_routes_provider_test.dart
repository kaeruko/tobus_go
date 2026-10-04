import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/providers/saved_routes_provider.dart';

Candidate _candidate(String id) {
  return Candidate(
    id: id,
    lines: const [],
    rides: 0,
    boards: 0,
    transfers: 0,
    total: 1,
    totalTime: 1,
    steps: const [],
    points: const [],
  );
}

void main() {
  test('favorites are ordered by saved time with newest first', () async {
    final older = _candidate('older');
    final newer = _candidate('newer');
    final legacyJson = jsonEncode([
      older.toJson(includeSavedRouteMemo: true),
      newer.toJson(includeSavedRouteMemo: true),
    ]);
    SharedPreferences.setMockInitialValues({'saved_routes': legacyJson});

    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(savedRoutesProvider);
    await pumpEventQueue();

    expect(
      container.read(savedRoutesProvider).map((route) => route.id),
      ['newer', 'older'],
    );
    expect(
      container
          .read(savedRoutesProvider)
          .every((route) => route.savedRouteSavedAt != null),
      isTrue,
    );

    await container.read(savedRoutesProvider.notifier).add(_candidate('newest'));

    expect(
      container.read(savedRoutesProvider).map((route) => route.id),
      ['newest', 'newer', 'older'],
    );

    final prefs = await SharedPreferences.getInstance();
    final persistedRaw = prefs.getString('saved_routes');
    expect(persistedRaw, isNotNull);
    final persisted = jsonDecode(persistedRaw!) as List<dynamic>;
    final savedAt = persisted
        .map(
          (item) => DateTime.parse(
            (item as Map<String, dynamic>)['saved_route_saved_at'] as String,
          ).toUtc(),
        )
        .toList();

    expect(savedAt[0].isAfter(savedAt[1]), isTrue);
    expect(savedAt[1].isAfter(savedAt[2]), isTrue);
  });
}
