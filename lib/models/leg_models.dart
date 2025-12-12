import 'route_models.dart';

// 経路の方向
enum LegDirection { outbound, inbound, other, unknown }

// 経路の状態
enum LegStatus { draft, confirmed }

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
    return Leg(
      direction: LegDirection.values.firstWhere(
        (e) => e.name == (json['direction'] as String?),
        orElse: () => LegDirection.unknown,
      ),
      status: LegStatus.values.firstWhere(
        (e) => e.name == (json['status'] as String?),
        orElse: () => LegStatus.confirmed,
      ),
      candidate: Candidate.fromJson(json['candidate'] as Map<String, dynamic>),
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
      confirmedAt: DateTime.now(),
    );
  }
}
