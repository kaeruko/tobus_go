import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../utils/string_utils.dart';

class RouteMeta {
  final bool destinationReachable;
  final String destinationLabel;
  final String? fallbackNodeName;
  final double? fallbackDistanceM;
  final int? walkLimitM;

  RouteMeta({
    required this.destinationReachable,
    required this.destinationLabel,
    this.fallbackNodeName,
    this.fallbackDistanceM,
    this.walkLimitM,
  });

  factory RouteMeta.fromJson(Map<String, dynamic> json) {
    return RouteMeta(
      destinationReachable: json['destination_reachable'] == true,
      destinationLabel: json['destination_label']?.toString() ?? '目的地',
      fallbackNodeName: json['fallback_node_name']?.toString(),
      fallbackDistanceM: (json['fallback_distance_m'] as num?)?.toDouble(),
      walkLimitM: (json['walk_limit_m'] as num?)?.toInt(),
    );
  }

  int? get fallbackWalkMinutes {
    if (fallbackDistanceM == null) return null;
    // Assume about 80m per minute walking speed
    return (fallbackDistanceM! / 80).ceil();
  }
}

class Candidate {
  final String id;
  final List<String> lines;
  final int rides;
  final int walks;
  final int boards;
  final int transfers;
  final int total;
  final int totalTime;
  final List<StepSeg> steps;
  final List<LatLng> points;
  final String? originName;
  final String? destinationName;
  final String? preference;
  final DateTime? departureDate;
  final bool isFutureSuggestion;
  final LatLng? originCoords;
  final LatLng? destinationCoords;
  final String? arrivalTime;

  Candidate({
    required this.id,
    required this.lines,
    required this.rides,
    required this.walks,
    required this.boards,
    required this.transfers,
    required this.total,
    required this.totalTime,
    required this.steps,
    required this.points,
    this.originName,
    this.destinationName,
    this.preference,
    this.departureDate,
    this.isFutureSuggestion = false,
    this.originCoords,
    this.destinationCoords,
    this.arrivalTime,
  });

  factory Candidate.fromJson(Map<String, dynamic> j) {
    final originName = j['origin_name']?.toString();
    final destinationName = j['destination_name']?.toString();

    return Candidate(
      id: j['id']?.toString() ?? '',
      lines: (j['lines'] is List) ? List<String>.from(j['lines']) : const [],
      rides: (j['rides'] as num? ?? 0).toInt(),
      walks: (j['walks'] as num? ?? 0).toInt(),
      boards: (j['boards'] as num? ?? 0).toInt(),
      transfers: (j['transfers'] as num? ?? 0).toInt(),
      total: (j['total'] as num? ?? 0).toInt(),
      totalTime: (j['total_time'] as num? ?? 0).toInt(),
      steps: _readSteps(j, originName, destinationName),
      points: (j['points'] as List?)
              ?.map((e) => (e is List && e.length >= 2)
                  ? LatLng((e[0] as num).toDouble(), (e[1] as num).toDouble())
                  : const LatLng(0, 0))
              .toList() ??
          const [],
      originName: originName,
      destinationName: destinationName,
      preference: j['preference']?.toString(),
      departureDate: j['departure_date'] != null
          ? DateTime.tryParse(j['departure_date'])
          : null,
      isFutureSuggestion: j['is_future_suggestion'] == true,
      originCoords: (j['origin_coords'] is List && j['origin_coords'].length >= 2)
          ? LatLng((j['origin_coords'][0] as num).toDouble(), (j['origin_coords'][1] as num).toDouble())
          : null,
      destinationCoords: (j['destination_coords'] is List && j['destination_coords'].length >= 2)
          ? LatLng((j['destination_coords'][0] as num).toDouble(), (j['destination_coords'][1] as num).toDouble())
          : null,
      arrivalTime: j['arrival_time']?.toString(),
    );
  }

  static List<StepSeg> _readSteps(Map<String, dynamic> j, String? originName, String? destinationName) {
    final out = <StepSeg>[];
    final raw = j['steps'];
    
    final simpleOrigin = originName != null ? StringUtils.extractSimpleName(originName) : null;
    final simpleDest = destinationName != null ? StringUtils.extractSimpleName(destinationName) : null;

    if (raw is List) {
      for (final item in raw) {
        if (item is Map) {
          final map = Map<String, dynamic>.from(item);
          // "現在地" / "目的地" の置換ロジック
          if ((map['from_'] == '現在地' || map['from'] == '現在地') && simpleOrigin != null) {
            map['from_'] = simpleOrigin;
            map['from'] = simpleOrigin;
          }
          if (map['to'] == '目的地' && simpleDest != null) {
            map['to'] = simpleDest;
          }

          out.add(StepSeg.fromJson(map));
        }
      }
    }
    return out;
  }

  Map<String, dynamic> toJson({bool includePoints = true}) {
    return {
      'id': id,
      'lines': lines,
      'rides': rides,
      'walks': walks,
      'boards': boards,
      'transfers': transfers,
      'total': total,
      'total_time': totalTime,
      'steps': steps.map((e) => e.toJson()).toList(),
      'points': includePoints
          ? points.map((e) => [e.latitude, e.longitude]).toList()
          : [],
      'origin_name': originName,
      'destination_name': destinationName,
      'preference': preference,
      'departure_date': departureDate?.toIso8601String(),
      'is_future_suggestion': isFutureSuggestion,
      'origin_coords': originCoords != null ? [originCoords!.latitude, originCoords!.longitude] : null,
      'destination_coords': destinationCoords != null ? [destinationCoords!.latitude, destinationCoords!.longitude] : null,
      'arrival_time': arrivalTime,
    };
  }
}

class StepSeg {
  final String kind;
  final String title;
  final int edges;
  final int? minutes;
  final int? meters;
  final int? fareYen;
  final String? from;
  final String? to;
  final String? departureTime;
  final String? arrivalTime;
  final String routeId;
  final String departureStopId;
  final String arrivalPoleId;
  final List<StopPoint> stops;

  StepSeg({
    required this.kind,
    required this.title,
    required this.edges,
    this.minutes,
    this.meters,
    this.fareYen,
    this.from,
    this.to,
    this.departureTime,
    this.arrivalTime,
    this.routeId = '',
    this.departureStopId = '',
    this.arrivalPoleId = '',
    List<StopPoint>? stops,
  }) : stops = stops ?? const [];

  factory StepSeg.fromJson(Map<String, dynamic> j) {
    final rawStops = j['stops'] as List? ?? const [];
    final stops = <StopPoint>[];
    for (final v in rawStops) {
      if (v is Map) {
        stops.add(StopPoint.fromJson(Map<String, dynamic>.from(v)));
      }
    }
    return StepSeg(
      kind: j['kind']?.toString() ?? 'bus',
      title: j['title']?.toString() ?? '',
      edges: (j['edges'] as num? ?? 0).toInt(),
      minutes: (j['minutes'] as num?)?.toInt(),
      meters: (j['meters'] as num?)?.toInt(),
      fareYen: (j['fareYen'] as num?)?.toInt(),
      from: j['from_']?.toString() ?? j['from']?.toString(),
      to: j['to']?.toString(),
      departureTime: j['departure_time']?.toString(),
      arrivalTime: j['arrival_time']?.toString(),
      // Use backend-provided GTFS IDs (empty string if not available)
      routeId: j['routeId']?.toString() ?? '',
      departureStopId: j['departureStopId']?.toString() ?? '',
      arrivalPoleId: j['arrivalPoleId']?.toString() ?? '',
      stops: stops,
    );
  }

  String get mainTitle => kind == 'walk' ? '徒歩' : title;
  String? get subTitle {
    if (kind == 'wait' && from != null) {
      return '$from で待機';
    }
    if (from != null && to != null) {
      return '$from → $to';
    }
    if (kind == 'walk') {
      if (meters != null)   return '徒歩 約${meters}m';
      if (minutes != null)  return '徒歩 約$minutes分';
      return '徒歩';
    }
    return null;
  }

  Map<String, dynamic> toJson() {
    return {
      'kind': kind,
      'title': title,
      'edges': edges,
      'minutes': minutes,
      'meters': meters,
      'fareYen': fareYen,
      'from_': from,
      'to': to,
      'departure_time': departureTime,
      'arrival_time': arrivalTime,
      'routeId': routeId,
      'departureStopId': departureStopId,
      'arrivalPoleId': arrivalPoleId,
      'stops': stops.map((e) => e.toJson()).toList(),
    };
  }
}

class StopPoint {
  final String name;
  final bool isOrigin;
  final bool isDestination;
  final double? lat;
  final double? lon;

  StopPoint({
    required this.name,
    this.isOrigin = false,
    this.isDestination = false,
    this.lat,
    this.lon,
  });

  factory StopPoint.fromJson(Map<String, dynamic> j) {
    return StopPoint(
      name: j['name']?.toString() ?? '',
      isOrigin: j['is_origin'] == true,
      isDestination: j['is_destination'] == true,
      lat: (j['lat'] as num?)?.toDouble(),
      lon: (j['lon'] as num?)?.toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'name': name,
      'is_origin': isOrigin,
      'is_destination': isDestination,
      'lat': lat,
      'lon': lon,
    };
  }
}
