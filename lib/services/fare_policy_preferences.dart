import 'package:shared_preferences/shared_preferences.dart';

import '../core/city_profile.dart';

class FarePolicyPreferences {
  static String _key(CityProfile profile) => 'farePolicyId:${profile.key}';

  static Future<String?> loadOptional(CityProfile profile) async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_key(profile));
    if (profile.city == AppCity.yokohama &&
        (stored == null || stored == 'normal')) {
      return null; // First use or legacy normal: require explicit selection.
    }
    final selected = stored ?? profile.defaultFarePolicyId;
    profile.farePolicyById(selected);
    return selected;
  }

  static Future<String> load(CityProfile profile) async {
    final selected = await loadOptional(profile);
    if (selected == null) {
      throw StateError('Yokohama fare pass must be explicitly selected');
    }
    return selected;
  }

  static Future<void> save(CityProfile profile, String policyId) async {
    profile.farePolicyById(policyId);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key(profile), policyId);
  }
}
