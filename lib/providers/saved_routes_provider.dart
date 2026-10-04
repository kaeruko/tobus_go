import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/route_models.dart';
import '../services/storage_service.dart';

class SavedRoutesNotifier extends StateNotifier<List<Candidate>> {
  static const int maxMemoLength = 500;

  SavedRoutesNotifier() : super([]) {
    _load();
  }

  final _storage = StorageService();

  Future<void> _load() async {
    final routes = await _storage.loadRoutes();
    if (routes.isEmpty) {
      state = const [];
      return;
    }

    final missingSavedAt = routes
        .where((route) => route.savedRouteSavedAt == null)
        .length;
    if (missingSavedAt != 0 && missingSavedAt != routes.length) {
      throw StateError(
        'お気に入りの保存時刻が一部だけ欠けています: '
        '$missingSavedAt/${routes.length}',
      );
    }

    var normalized = routes;
    final needsMigration = missingSavedAt == routes.length;
    if (needsMigration) {
      final legacyBase = DateTime.utc(2000, 1, 1);
      normalized = [
        for (var index = 0; index < routes.length; index++)
          routes[index].withSavedRouteSavedAt(
            legacyBase.add(Duration(microseconds: index)),
          ),
      ];
    }

    final sorted = _sortNewestFirst(normalized);
    if (needsMigration) {
      await _storage.saveRoutes(sorted);
    }
    state = sorted;
  }

  Future<void> add(Candidate route) async {
    final savedRoute = route.withSavedRouteSavedAt(DateTime.now().toUtc());
    final newState = _sortNewestFirst([...state, savedRoute]);
    await _storage.saveRoutes(newState);
    state = newState;
  }

  List<Candidate> _sortNewestFirst(Iterable<Candidate> routes) {
    final sorted = routes.toList();
    for (final route in sorted) {
      if (route.savedRouteSavedAt == null) {
        throw StateError('お気に入りの保存時刻がありません: routeId=${route.id}');
      }
    }
    sorted.sort(
      (a, b) => b.savedRouteSavedAt!.compareTo(a.savedRouteSavedAt!),
    );
    return sorted;
  }

  Future<void> remove(Candidate route) async {
    state = state.where((r) => r != route).toList(); // Ensure equality works or use specific ID if available
    await _storage.saveRoutes(state);
  }
  
  // For removing by index if equality is tricky
  Future<void> removeAt(int index) async {
    if (index >= 0 && index < state.length) {
      final newState = List<Candidate>.from(state);
      newState.removeAt(index);
      state = newState;
      await _storage.saveRoutes(state);
    }
  }

  Future<void> removeWhere(bool Function(Candidate) test) async {
    state = state.where((item) => !test(item)).toList();
    await _storage.saveRoutes(state);
  }

  Future<void> updateMemo(int index, String memo) async {
    if (index < 0 || index >= state.length) {
      throw RangeError.index(index, state, 'index');
    }

    final normalized = memo.trim();
    if (normalized.length > maxMemoLength) {
      throw ArgumentError.value(
        memo,
        'memo',
        'お気に入り経路のメモは$maxMemoLength文字以内で入力してください',
      );
    }

    final newState = List<Candidate>.from(state);
    newState[index] = newState[index].withSavedRouteMemo(
      normalized.isEmpty ? null : normalized,
    );
    await _storage.saveRoutes(newState);
    state = newState;
  }
}

final savedRoutesProvider = StateNotifierProvider<SavedRoutesNotifier, List<Candidate>>((ref) {
  return SavedRoutesNotifier();
});
