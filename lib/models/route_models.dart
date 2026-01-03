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
              ?.map((e) {
                if (e is List && e.length >= 2) {
                   final lat = e[0] as num?;
                   final lon = e[1] as num?;
                   if (lat != null && lon != null) {
                     return LatLng(lat.toDouble(), lon.toDouble());
                   }
                }
                return const LatLng(0, 0);
              })
              .toList() ??
          const [],
      originName: originName,
      destinationName: destinationName,
      preference: j['preference']?.toString(),
      departureDate: j['departure_date'] != null
          ? DateTime.tryParse(j['departure_date'])
          : null,
      isFutureSuggestion: j['is_future_suggestion'] == true,
      originCoords: (j['origin_coords'] is List && j['origin_coords'].length >= 2 && j['origin_coords'][0] != null && j['origin_coords'][1] != null)
          ? LatLng((j['origin_coords'][0] as num).toDouble(), (j['origin_coords'][1] as num).toDouble())
          : null,
      destinationCoords: (j['destination_coords'] is List && j['destination_coords'].length >= 2 && j['destination_coords'][0] != null && j['destination_coords'][1] != null)
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
  final String kind; // 'walk', 'bus', 'rail', 'wait'
  final String title;
  final String? fromName;
  final String? toName;
  final List<StopPoint> stops;
  final int minutes;
  final double meters;
  final int? fareYen; // keep existing optional fields
  final String? departureTime;
  final String? arrivalTime;
  final String? startLabel;
  final String? endLabel;
  final String? place;
  
  final String? routeId;     // 系統ID
  final String? tripId;      // 便ID (GTFS-RTとの紐付け用)
  final String? directionId; // 方向ID

  // Compatibility / Legacy fields
  final int edges;
  final String departureStopId;
  final String arrivalPoleId;

  StepSeg({
    required this.kind,
    required this.title,
    this.fromName,
    this.toName,
    this.stops = const [],
    this.minutes = 0,
    this.meters = 0.0,
    this.fareYen,
    this.departureTime,
    this.arrivalTime,
    this.startLabel,
    this.endLabel,
    this.place,
    this.routeId,     // ★
    this.tripId,      // ★
    this.directionId, // ★
    this.edges = 0,
    this.departureStopId = '',
    this.arrivalPoleId = '',
  });

  bool get isRide => kind == 'bus' || kind == 'rail';

  // Keep getters for compatibility if needed, or rely on public fields
  String? get from => fromName;
  String? get to => toName;

  factory StepSeg.fromJson(Map<String, dynamic> json) {
    var rawStops = json['stops'] as List? ?? [];
    var parsedStops = rawStops.map((e) => StopPoint.fromJson(Map<String, dynamic>.from(e))).toList();

    return StepSeg(
      kind: json['kind'] ?? 'walk',
      title: json['title'] ?? '',
      fromName: json['from_'] ?? json['from'],
      toName: json['to'],
      stops: parsedStops,
      minutes: json['minutes'] ?? 0,
      meters: (json['meters'] as num?)?.toDouble() ?? 0.0,
      fareYen: (json['fareYen'] as num?)?.toInt(),
      departureTime: json['departure_time'],
      arrivalTime: json['arrival_time'],
      startLabel: json['startLabel'],
      endLabel: json['endLabel'],
      place: json['place'],
      
      // ★追加: IDパース
      routeId: json['route_id'] ?? json['routeId'], // Handle both snake and camel if possible, user snippet used snake
      tripId: json['trip_id'],
      directionId: json['direction_id'],
      
      // Legacy
      edges: (json['edges'] as num? ?? 0).toInt(),
      departureStopId: json['departureStopId']?.toString() ?? '',
      arrivalPoleId: json['arrivalPoleId']?.toString() ?? '',
    );
  }
  
  String get mainTitle => kind == 'walk' ? '徒歩' : title;
  String? get subTitle {
    if (kind == 'wait') {
      if (startLabel != null || endLabel != null) {
        return place ?? fromName ?? '待機場所';
      }
      if (fromName != null) return '$fromName で待機';
    }
    if (fromName != null && toName != null) {
      return '$fromName → $toName';
    }
    if (kind == 'walk') {
      if (meters > 0)   return '徒歩 約${meters.toInt()}m';
      if (minutes > 0)  return '徒歩 約$minutes分';
      return '徒歩';
    }
    return null;
  }

  Map<String, dynamic> toJson() {
    return {
      'kind': kind,
      'title': title,
      'from_': fromName,
      'to': toName,
      'stops': stops.map((e) => e.toJson()).toList(),
      'minutes': minutes,
      'meters': meters,
      'fareYen': fareYen,
      'departure_time': departureTime,
      'arrival_time': arrivalTime,
      'startLabel': startLabel,
      'endLabel': endLabel,
      'place': place,
      'route_id': routeId,
      'trip_id': tripId,
      'direction_id': directionId,
      'edges': edges,
      'departureStopId': departureStopId,
      'arrivalPoleId': arrivalPoleId,
    };
  }
}

class StopPoint {
  final String name;
  final LatLng point;
  final bool isOrigin;
  final bool isDestination;
  final String? stopId; // ★追加: 停留所ID (odpt:BusstopPole:...)

  StopPoint({
    required this.name,
    required this.point,
    this.isOrigin = false,
    this.isDestination = false,
    this.stopId, // ★追加
  });

  factory StopPoint.fromJson(Map<String, dynamic> json) {
    return StopPoint(
      name: json['name'] ?? '',
      point: LatLng(
        (json['lat'] as num?)?.toDouble() ?? 0.0,
        (json['lon'] as num?)?.toDouble() ?? 0.0,
      ),
      isOrigin: json['is_origin'] ?? false,
      isDestination: json['is_destination'] ?? false,
      stopId: json['stop_id'] ?? json['id'], // ★追加: バックエンドが返すJSONのキーに合わせて調整
    );
  }

  // Compatibility getters
  double get lat => point.latitude;
  double get lon => point.longitude;

  Map<String, dynamic> toJson() {
    return {
      'name': name,
      'is_origin': isOrigin,
      'is_destination': isDestination,
      'lat': point.latitude,
      'lon': point.longitude,
      'id': stopId,
    };
  }
}
