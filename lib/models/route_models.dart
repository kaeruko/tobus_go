import 'package:google_maps_flutter/google_maps_flutter.dart';

class Candidate {
  final String id;
  final List<String> lines;
  final int rides;
  final int walks;
  final int boards;
  final int transfers;
  final int total;
  final List<StepSeg> steps;
  final List<LatLng> points;
  final String? preference;
  final DateTime? departureDate;
  final bool isFutureSuggestion;

  Candidate({
    required this.id,
    required this.lines,
    required this.rides,
    required this.walks,
    required this.boards,
    required this.transfers,
    required this.total,
    required this.steps,
    required this.points,
    this.preference,
    this.departureDate,
    this.isFutureSuggestion = false,
  });

  factory Candidate.fromJson(Map<String, dynamic> j) {
    return Candidate(
      id: j['id']?.toString() ?? '',
      lines: (j['lines'] is List) ? List<String>.from(j['lines']) : const [],
      rides: (j['rides'] as num? ?? 0).toInt(),
      walks: (j['walks'] as num? ?? 0).toInt(),
      boards: (j['boards'] as num? ?? 0).toInt(),
      transfers: (j['transfers'] as num? ?? 0).toInt(),
      total: (j['total'] as num? ?? 0).toInt(),
      steps: _readSteps(j),
      points: (j['points'] as List?)
              ?.map((e) => (e is List && e.length >= 2)
                  ? LatLng((e[0] as num).toDouble(), (e[1] as num).toDouble())
                  : const LatLng(0, 0))
              .toList() ??
          const [],
      preference: j['preference']?.toString(),
      departureDate: j['departure_date'] != null
          ? DateTime.tryParse(j['departure_date'])
          : null,
      isFutureSuggestion: j['is_future_suggestion'] == true,
    );
  }

  static List<StepSeg> _readSteps(Map<String, dynamic> j) {
    final out = <StepSeg>[];
    final raw = j['steps'];
    if (raw is List) {
      for (final item in raw) {
        if (item is Map) {
          out.add(StepSeg.fromJson(Map<String, dynamic>.from(item)));
        }
      }
    }
    return out;
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'lines': lines,
      'rides': rides,
      'walks': walks,
      'boards': boards,
      'transfers': transfers,
      'total': total,
      'steps': steps.map((e) => e.toJson()).toList(),
      'points': points.map((e) => [e.latitude, e.longitude]).toList(),
      'preference': preference,
      'departure_date': departureDate?.toIso8601String(),
      'is_future_suggestion': isFutureSuggestion,
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
      stops: stops,
    );
  }

  String get mainTitle => kind == 'walk' ? '徒歩' : title;
  String? get subTitle {
    if (from != null && to != null) {
      if (kind == 'walk') {
        String extra = '';
        if (minutes != null) {
          extra = '（約$minutes分）';
        } else if (meters != null) {
          extra = '（約${meters}m）';
        }
        return '$from → $to$extra';
      }
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
      'stops': stops.map((e) => e.toJson()).toList(),
    };
  }
}

class StopPoint {
  final String name;
  final bool isOrigin;
  final bool isDestination;

  StopPoint({required this.name, this.isOrigin = false, this.isDestination = false});

  factory StopPoint.fromJson(Map<String, dynamic> j) {
    return StopPoint(
      name: j['name']?.toString() ?? '',
      isOrigin: j['is_origin'] == true,
      isDestination: j['is_destination'] == true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'name': name,
      'is_origin': isOrigin,
      'is_destination': isDestination,
    };
  }
}
