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

class FarePolicyOption {
  final String id;
  final String displayName;
  final String settlementType;
  final String? sourceUri;

  const FarePolicyOption({
    required this.id,
    required this.displayName,
    required this.settlementType,
    this.sourceUri,
  });
}

class CityProfile {
  final AppCity city;
  final String key;
  final String appName;
  final CityCapabilities capabilities;
  final List<FarePolicyOption> farePolicies;
  final String defaultFarePolicyId;

  const CityProfile({
    required this.city,
    required this.key,
    required this.appName,
    required this.capabilities,
    required this.farePolicies,
    this.defaultFarePolicyId = 'normal',
  });

  FarePolicyOption farePolicyById(String id) {
    for (final option in farePolicies) {
      if (option.id == id) return option;
    }
    throw StateError(
      'Unsupported fare policy for $key: "$id". '
      'Expected one of: ${farePolicies.map((e) => e.id).join(', ')}',
    );
  }
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
  farePolicies: [
    FarePolicyOption(
      id: 'normal',
      displayName: '通常運賃',
      settlementType: 'normal',
    ),
    FarePolicyOption(
      id: 'tokyo_toei_transport_pass',
      displayName: '精神障害者都営交通乗車証',
      settlementType: 'free_pass',
      sourceUri:
          'https://www.fukushi.metro.tokyo.lg.jp/shougai/nichijo/jousyasyo',
    ),
  ],
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
  farePolicies: [
    FarePolicyOption(
      id: 'normal',
      displayName: '通常運賃',
      settlementType: 'normal',
    ),
    FarePolicyOption(
      id: 'nagoya_welfare_special_pass',
      displayName: '福祉特別乗車券（無料乗車区間）',
      settlementType: 'free_pass',
      sourceUri:
          'https://www.city.nagoya.jp/kenkofukushi/shougaisha/1016573/1016578.html',
    ),
  ],
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
  farePolicies: [
    FarePolicyOption(
      id: 'normal',
      displayName: '通常運賃',
      settlementType: 'normal',
    ),
  ],
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
