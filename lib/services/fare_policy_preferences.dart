import 'package:shared_preferences/shared_preferences.dart';

import '../core/city_profile.dart';

class FarePolicyPreferences {
  static String _key(CityProfile profile) => 'farePolicyId:${profile.key}';

  static Future<String> load(CityProfile profile) async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_key(profile));
    if (stored == null) return profile.defaultFarePolicyId;
    profile.farePolicyById(stored);
    return stored;
  }

  static Future<void> save(CityProfile profile, String policyId) async {
    profile.farePolicyById(policyId);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key(profile), policyId);
  }
}
