import '../core/app_clock.dart';
import 'route_models.dart';

// 経路の方向
enum LegDirection { outbound, inbound, other, unknown }

// 経路の状態
enum LegStatus { draft, confirmed }

List<double>? _readCoordinatePair(dynamic raw) {
  if (raw is! List || raw.length < 2) return null;
  final lat = raw[0];
  final lon = raw[1];
  if (lat is! num || lon is! num) return null;
  return [lat.toDouble(), lon.toDouble()];
}

void _appendUniquePoint(List<List<double>> points, List<double> next) {
  if (points.isNotEmpty) {
    final previous = points.last;
    if (previous[0] == next[0] && previous[1] == next[1]) {
      return;
    }
  }
  points.add(next);
}

void _restorePersistedCandidatePoints(Map<String, dynamic> candidateJson) {
  final rawPoints = candidateJson['points'];
  if (rawPoints is List && rawPoints.isNotEmpty) return;

  final origin = _readCoordinatePair(candidateJson['origin_coords']);
  final destination = _readCoordinatePair(candidateJson['destination_coords']);
  if (origin == null || destination == null) return;

  final restored = <List<double>>[];
  _appendUniquePoint(restored, origin);

  final rawSteps = candidateJson['steps'];
  if (rawSteps is List) {
    for (final rawStep in rawSteps) {
      if (rawStep is! Map) continue;
      final step = Map<String, dynamic>.from(rawStep);
      final rawStops = step['stops'];
      if (rawStops is! List) continue;

      for (final rawStop in rawStops) {
        if (rawStop is! Map) continue;
        final stop = Map<String, dynamic>.from(rawStop);
        final lat = stop['lat'];
        final lon = stop['lon'];
        if (lat is num && lon is num) {
          _appendUniquePoint(restored, [lat.toDouble(), lon.toDouble()]);
        }
      }
    }
  }

  _appendUniquePoint(restored, destination);
  candidateJson['points'] = restored;
}

class Leg {
  final LegDirection direction;
  final LegStatus status;
  final Candidate candidate;
  final DateTime? confirmedAt;

  const Leg({
    required this.direction,
    required this.status,
    required this.candidate,
    this.confirmedAt,
  });

  factory Leg.fromJson(Map<String, dynamic> json) {
    final rawCandidate = json['candidate'];
    if (rawCandidate is! Map) {
      throw const FormatException('leg is missing required candidate data');
    }

    final candidateJson = Map<String, dynamic>.from(rawCandidate);
    _restorePersistedCandidatePoints(candidateJson);

    return Leg(
      direction: LegDirection.values.firstWhere(
        (e) => e.name == (json['direction'] as String?),
        orElse: () => LegDirection.unknown,
      ),
      status: LegStatus.values.firstWhere(
        (e) => e.name == (json['status'] as String?),
        orElse: () => LegStatus.confirmed,
      ),
      candidate: Candidate.fromJson(candidateJson),
      confirmedAt: json['confirmedAt'] != null
          ? DateTime.tryParse(json['confirmedAt'] as String)
          : null,
    );
  }

  Map<String, dynamic> toJson({bool includePoints = true}) {
    return {
      'direction': direction.name,
      'status': status.name,
      'candidate': candidate.toJson(includePoints: includePoints),
      'confirmedAt': confirmedAt?.toIso8601String(),
    };
  }
}

class LegDraft {
  LegDirection direction;
  Candidate candidate;
  LegStatus status;

  LegDraft({
    required this.direction,
    required this.candidate,
    this.status = LegStatus.draft,
  });

  Leg toLeg() {
    return Leg(
      direction: direction,
      status: status == LegStatus.draft ? LegStatus.confirmed : status,
      candidate: candidate,
      confirmedAt: appClock.now(),
    );
  }
}
