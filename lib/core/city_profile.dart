import 'package:flutter/services.dart' show appFlavor;

enum AppCity {
  tokyo,
  nagoya,
  sendai,
  yokohama,
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

class CityDistributionConfig {
  final String androidApplicationId;
  final String iosBundleIdentifier;
  final bool firebaseEnabled;
  final String storeMetadataDirectory;

  const CityDistributionConfig({
    required this.androidApplicationId,
    required this.iosBundleIdentifier,
    required this.firebaseEnabled,
    required this.storeMetadataDirectory,
  });
}

class CityProfile {
  final AppCity city;
  final String key;
  final String appName;
  final CityCapabilities capabilities;
  final List<FarePolicyOption> farePolicies;
  final String defaultFarePolicyId;
  final CityDistributionConfig distribution;

  const CityProfile({
    required this.city,
    required this.key,
    required this.appName,
    required this.capabilities,
    required this.farePolicies,
    required this.distribution,
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
  distribution: CityDistributionConfig(
    androidApplicationId: 'jp.cloxs.toeigo',
    iosBundleIdentifier: 'jp.cloxs.go.tokyo',
    firebaseEnabled: true,
    storeMetadataDirectory: 'store/tokyo',
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
  distribution: CityDistributionConfig(
    androidApplicationId: 'jp.cloxs.nagoyago',
    iosBundleIdentifier: 'jp.cloxs.nagoyago',
    firebaseEnabled: false,
    storeMetadataDirectory: 'store/nagoya',
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
  farePolicies: [
    FarePolicyOption(
      id: 'normal',
      displayName: '通常運賃',
      settlementType: 'normal',
    ),
  ],
  distribution: CityDistributionConfig(
    androidApplicationId: 'jp.cloxs.sendaigo',
    iosBundleIdentifier: 'jp.cloxs.sendaigo',
    firebaseEnabled: false,
    storeMetadataDirectory: 'store/sendai',
  ),
);

const yokohamaCityProfile = CityProfile(
  city: AppCity.yokohama,
  key: 'yokohama',
  appName: '横浜でGO',
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
  ],
  distribution: CityDistributionConfig(
    androidApplicationId: 'jp.cloxs.yokohamago',
    iosBundleIdentifier: 'jp.cloxs.yokohamago',
    firebaseEnabled: false,
    storeMetadataDirectory: 'store/yokohama',
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
    case 'yokohama':
      return yokohamaCityProfile;
    default:
      throw StateError(
        'Unsupported APP_CITY="$key". Expected one of: tokyo, nagoya, sendai, yokohama',
      );
  }
}

const _configuredCityDefine = String.fromEnvironment(
  'APP_CITY',
  defaultValue: '',
);

String resolveConfiguredCityKey({
  String? flavor,
  String dartDefine = _configuredCityDefine,
}) {
  if (flavor != null && flavor.trim() != flavor) {
    throw StateError('Invalid app flavor with surrounding whitespace: "$flavor"');
  }
  if (dartDefine.trim() != dartDefine) {
    throw StateError(
      'Invalid APP_CITY with surrounding whitespace: "$dartDefine"',
    );
  }

  final flavorKey = flavor ?? '';
  if (flavorKey.isNotEmpty) {
    cityProfileForKey(flavorKey);
  }
  if (dartDefine.isNotEmpty) {
    cityProfileForKey(dartDefine);
  }
  if (flavorKey.isNotEmpty &&
      dartDefine.isNotEmpty &&
      flavorKey != dartDefine) {
    throw StateError(
      'Flavor/APP_CITY mismatch: flavor="$flavorKey", APP_CITY="$dartDefine"',
    );
  }

  if (flavorKey.isNotEmpty) return flavorKey;
  if (dartDefine.isNotEmpty) return dartDefine;

  // Tests and legacy local development without --flavor remain Tokyo.
  // Store builds are flavor-specific and therefore do not take this branch.
  return 'tokyo';
}

String get configuredCityKey => resolveConfiguredCityKey(flavor: appFlavor);

CityProfile get configuredCityProfile => cityProfileForKey(configuredCityKey);
