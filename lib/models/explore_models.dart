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