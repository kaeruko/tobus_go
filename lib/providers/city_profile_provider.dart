import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/city_profile.dart';

final cityProfileProvider = Provider<CityProfile>((ref) {
  return configuredCityProfile;
});
