enum AppCity {
  tokyo,
  nagoya,
  sendai,
}

class RealtimeCapabilities {
  final bool vehiclePosition;
  final bool tripUpdates;
  final bool alerts;

  const RealtimeCapabilities({
    required this.vehiclePosition,
    required this.tripUpdates,
    required this.alerts,
  });
}

class FeatureCapabilities {
  final bool routeSearchOnly;
  final bool outingDiscovery;
  final bool savedRoutes;
  final bool history;
  final bool groupTrips;

  const FeatureCapabilities({
    required this.routeSearchOnly,
    required this.outingDiscovery,
    required this.savedRoutes,
    required this.history,
    required this.groupTrips,
  });
}

class CityCapabilities {
  final FeatureCapabilities features;
  final RealtimeCapabilities realtime;

  const CityCapabilities({
    required this.features,
    required this.realtime,
  });
}

class CityProfile {
  final AppCity city;
  final String key;
  final String appName;
  final CityCapabilities capabilities;

  const CityProfile({
    required this.city,
    required this.key,
    required this.appName,
    required this.capabilities,
  });
}

const tokyoCityProfile = CityProfile(
  city: AppCity.tokyo,
  key: 'tokyo',
  appName: '都営でGO',
  capabilities: CityCapabilities(
    features: FeatureCapabilities(
      routeSearchOnly: false,
      outingDiscovery: true,
      savedRoutes: true,
      history: true,
      groupTrips: true,
    ),
    realtime: RealtimeCapabilities(
      vehiclePosition: true,
      tripUpdates: false,
      alerts: false,
    ),
  ),
);

const nagoyaCityProfile = CityProfile(
  city: AppCity.nagoya,
  key: 'nagoya',
  appName: '名古屋でGO',
  capabilities: CityCapabilities(
    features: FeatureCapabilities(
      routeSearchOnly: true,
      outingDiscovery: false,
      savedRoutes: false,
      history: false,
      groupTrips: false,
    ),
    realtime: RealtimeCapabilities(
      vehiclePosition: false,
      tripUpdates: false,
      alerts: false,
    ),
  ),
);

const sendaiCityProfile = CityProfile(
  city: AppCity.sendai,
  key: 'sendai',
  appName: '仙台でGO',
  capabilities: CityCapabilities(
    features: FeatureCapabilities(
      routeSearchOnly: true,
      outingDiscovery: false,
      savedRoutes: false,
      history: false,
      groupTrips: false,
    ),
    realtime: RealtimeCapabilities(
      vehiclePosition: true,
      tripUpdates: true,
      alerts: true,
    ),
  ),
);

CityProfile cityProfileForKey(String key) {
  switch (key) {
    case 'tokyo':
      return tokyoCityProfile;
    case 'nagoya':
      return nagoyaCityProfile;
    case 'sendai':
      return sendaiCityProfile;
    default:
      throw StateError(
        'Unsupported APP_CITY="$key". Expected one of: tokyo, nagoya, sendai',
      );
  }
}

const configuredCityKey = String.fromEnvironment(
  'APP_CITY',
  defaultValue: 'tokyo',
);

final configuredCityProfile = cityProfileForKey(configuredCityKey);
