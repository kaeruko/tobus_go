import 'package:shared_preferences/shared_preferences.dart';

import '../core/city_profile.dart';

class FarePolicyPreferences {
  static String _key(CityProfile profile) => 'farePolicyId:${profile.key}';

  static Future<String> load(CityProfile profile) async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_key(profile));
    final selected = stored ?? profile.defaultFarePolicyId;
    profile.farePolicyById(selected);
    return selected;
  }

  static Future<void> save(CityProfile profile, String policyId) async {
    profile.farePolicyById(policyId);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key(profile), policyId);
  }
}
