class ReachableStop {
  final String id;
  final String name;
  final double lat;
  final double lon;
  final String viaRoute; // 系統ID (例: odpt.Busroute:Toei.Higashi22)

  ReachableStop({
    required this.id,
    required this.name,
    required this.lat,
    required this.lon,
    required this.viaRoute,
  });

  factory ReachableStop.fromJson(Map<String, dynamic> json) {
    return ReachableStop(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      lat: (json['lat'] as num?)?.toDouble() ?? 0.0,
      lon: (json['lon'] as num?)?.toDouble() ?? 0.0,
      viaRoute: json['via_route'] as String? ?? '',
    );
  }
}

class NearestStop {
  final String id;
  final String name;
  final double lat;
  final double lon;
  final double distM;

  NearestStop({
    required this.id,
    required this.name,
    required this.lat,
    required this.lon,
    required this.distM,
  });

  factory NearestStop.fromJson(Map<String, dynamic> json) {
    return NearestStop(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      lat: (json['lat'] as num?)?.toDouble() ?? 0.0,
      lon: (json['lon'] as num?)?.toDouble() ?? 0.0,
      distM: (json['dist_m'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class ReachableResponse {
  final bool found;
  final String? message;
  final NearestStop? nearestStop;
  final List<ReachableStop> reachableStops;

  ReachableResponse({
    required this.found,
    this.message,
    this.nearestStop,
    required this.reachableStops,
  });

  factory ReachableResponse.fromJson(Map<String, dynamic> json) {
    return ReachableResponse(
      found: json['found'] as bool? ?? false,
      message: json['message'] as String?,
      nearestStop: json['nearest_stop'] != null
          ? NearestStop.fromJson(json['nearest_stop'] as Map<String, dynamic>)
          : null,
      reachableStops: (json['reachable_stops'] as List<dynamic>?)
              ?.map((e) => ReachableStop.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
    );
  }
}

class ExperienceGroup {
  final List<String> tags;
  final String description;
  final ReachableStop representativeStop;
  final int stopCount;
  final List<ReachableStop> stops;

  ExperienceGroup({
    required this.tags,
    required this.description,
    required this.representativeStop,
    required this.stopCount,
    required this.stops,
  });

    factory ExperienceGroup.fromJson(Map<String, dynamic> json) {
    // representative_stop uses similar structure to ReachableStop but might lack viaRoute
    // Backend: "representative_stop": {"stop_id":..., "stop_name":..., "lat":..., "lon":...}
    final repData = json['representative_stop'] as Map<String, dynamic>;
    
    // Convert backend specific keys to ReachableStop keys if needed, or construct directly
    final representativeStop = ReachableStop(
      id: repData['stop_id'] as String? ?? '',
      name: repData['stop_name'] as String? ?? '',
      lat: (repData['lat'] as num?)?.toDouble() ?? 0.0,
      lon: (repData['lon'] as num?)?.toDouble() ?? 0.0,
      viaRoute: '', // Not provided in experience context
    );

    final stopsList = (json['stops'] as List<dynamic>?)?.map((s) {
       final m = s as Map<String, dynamic>;
       // backend stops list only has id and name
       // we might not need full ReachableStop here, but for reusing model...
       return ReachableStop(
         id: m['stop_id'] ?? '', 
         name: m['stop_name'] ?? '', 
         lat: 0, 
         lon: 0, 
         viaRoute: ''
       );
    }).toList() ?? [];

    return ExperienceGroup(
      tags: (json['tags'] as List<dynamic>?)?.map((e) => e.toString()).toList() ?? [],
      description: json['description'] as String? ?? '',
      representativeStop: representativeStop,
      stopCount: json['stop_count'] as int? ?? 0,
      stops: stopsList,
    );
  }
}

class ExperienceResponse {
  final List<ExperienceGroup> groups;

  ExperienceResponse({required this.groups});

  factory ExperienceResponse.fromJson(Map<String, dynamic> json) {
    return ExperienceResponse(
      groups: (json['groups'] as List<dynamic>?)
          ?.map((e) => ExperienceGroup.fromJson(e as Map<String, dynamic>))
          .toList() ?? [],
    );
  }
}