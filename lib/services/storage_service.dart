import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/route_models.dart';

class StorageService {
  static const String _keyRoutes = 'saved_routes';

  Future<void> saveRoutes(List<Candidate> routes) async {
    final prefs = await SharedPreferences.getInstance();
    final jsonList = routes.map((e) => e.toJson()).toList();
    final jsonString = jsonEncode(jsonList);
    await prefs.setString(_keyRoutes, jsonString);
  }

  Future<List<Candidate>> loadRoutes() async {
    final prefs = await SharedPreferences.getInstance();
    final jsonString = prefs.getString(_keyRoutes);
    if (jsonString == null) return [];

    try {
      final List<dynamic> jsonList = jsonDecode(jsonString);
      return jsonList
          .map((e) => Candidate.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      print('Error loading routes: $e');
      return [];
    }
  }
}
