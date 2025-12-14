import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/route_models.dart';
import '../services/storage_service.dart';

class SavedRoutesNotifier extends StateNotifier<List<Candidate>> {
  SavedRoutesNotifier() : super([]) {
    _load();
  }

  final _storage = StorageService();

  Future<void> _load() async {
    final routes = await _storage.loadRoutes();
    state = routes;
  }

  Future<void> add(Candidate route) async {
    state = [...state, route];
    await _storage.saveRoutes(state);
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
}

final savedRoutesProvider = StateNotifierProvider<SavedRoutesNotifier, List<Candidate>>((ref) {
  return SavedRoutesNotifier();
});
