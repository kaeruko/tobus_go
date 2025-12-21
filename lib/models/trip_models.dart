import 'package:cloud_firestore/cloud_firestore.dart';
import 'route_models.dart';
import 'group_models.dart';
import 'leg_models.dart';
import '../utils/string_utils.dart';

enum TravelPhase {
  planning,
  active,
  completed,
  cancelled,
}

// 旧コード互換用
enum TripStatus {
  planning,
  active,
  completed,
  cancelled,
}

class Trip {
  final String id;
  final String joinCode;
  final String leaderId;
  final String title;
  final TravelPhase travelPhase;
  final DateTime date;
  final DateTime? plannedDepartureAt;
  final DateTime? actualDepartureAt;
  final List<Leg> legs;
  final List<ScheduleEntry> schedule;
  final List<Participant> participants;
  final List<String> memberIds;
  final int completedLegIndex;

  TripStatus get status => TripStatus.values[travelPhase.index];

  int get activeLegIndex => completedLegIndex + 1;

  Trip({
    required this.id,
    required this.joinCode,
    required this.leaderId,
    required this.title,
    required this.travelPhase,
    required this.date,
    required this.plannedDepartureAt,
    required this.actualDepartureAt,
    required this.legs,
    required this.schedule,
    required this.participants,
    required this.memberIds,
    this.completedLegIndex = -1,
  });

  factory Trip.fromFirestore(DocumentSnapshot doc) {
    final data = doc.data() as Map<String, dynamic>;

    List<Leg> loadedLegs = [];
    if (data['legs'] != null) {
      loadedLegs = (data['legs'] as List<dynamic>)
          .map((e) => Leg.fromJson(e as Map<String, dynamic>))
          .toList();
    }

    final phaseName = data['travelPhase'] as String? ?? data['status'] as String?;

    return Trip(
      id: doc.id,
      joinCode: data['joinCode'] ?? '',
      leaderId: data['leaderId'] ?? '',
      title: data['title'] ?? '',
      travelPhase: TravelPhase.values.firstWhere(
        (e) => e.name == phaseName,
        orElse: () => TravelPhase.planning,
      ),
      date: (data['date'] as Timestamp).toDate(),
      plannedDepartureAt:
          (data['plannedDepartureAt'] as Timestamp?)?.toDate(),
      actualDepartureAt: (data['actualDepartureAt'] as Timestamp?)?.toDate(),
      legs: loadedLegs,
      schedule: (data['schedule'] as List<dynamic>? ?? [])
          .map((e) => ScheduleEntry.fromJson(e as Map<String, dynamic>))
          .toList(),
      participants: (data['participants'] as List<dynamic>? ?? [])
          .map((e) => Participant.fromJson(e as Map<String, dynamic>))
          .toList(),
      memberIds:
          (data['memberIds'] as List<dynamic>? ?? []).map((e) => e.toString()).toList(),
      completedLegIndex: data['completedLegIndex'] as int? ?? -1,
    );
  }

  Map<String, dynamic> toFirestore() {
    return {
      'joinCode': joinCode,
      'leaderId': leaderId,
      'title': title,
      'travelPhase': travelPhase.name,
      'status': travelPhase.name,
      'date': Timestamp.fromDate(date),
      'plannedDepartureAt': plannedDepartureAt != null
          ? Timestamp.fromDate(plannedDepartureAt!)
          : null,
      'actualDepartureAt': actualDepartureAt != null
          ? Timestamp.fromDate(actualDepartureAt!)
          : null,
      'legs': legs.map((e) => e.toJson(includePoints: false)).toList(),
      'schedule': schedule.map((e) => e.toJson()).toList(),
      'participants': participants.map((e) => e.toJson()).toList(),
      'memberIds': memberIds,
      'completedLegIndex': completedLegIndex,
  static String generateDisplayTitle(List<Leg> legs, String fallbackTitle) {
    // タイトル生成ロジック
    if (legs.isNotEmpty) {
      final outboundLeg = legs.firstWhere(
            (l) => l.direction == LegDirection.outbound,
        orElse: () => legs.first,
      );
      final destName = outboundLeg.candidate.destinationName;
      if (destName != null && destName.isNotEmpty && destName != '目的地') {
        // 住所などが含まれる長い名称の場合、最後の部分（施設名など）を採用する
        // 例: "日本、東京都中央区銀座7 銀座駅" -> "銀座駅"
        final simpleName = StringUtils.extractSimpleName(destName);
        return "$simpleName への遠足";
      }
    }
    return fallbackTitle;
  }

  String get displayTitle => generateDisplayTitle(legs, title);
}

class Participant {
  final String uid;
  final String name;
  final bool isLeader;
  final int? stepCount;
  final int? sosCount;
  final String? memo;

  Participant({
    required this.uid,
    required this.name,
    this.isLeader = false,
    this.stepCount,
    this.sosCount,
    this.memo,
  });

  factory Participant.fromJson(Map<String, dynamic> json) {
    return Participant(
      uid: json['uid'] ?? '',
      name: json['name'] ?? '',
      isLeader: json['isLeader'] ?? false,
      stepCount: json['stepCount'] as int?,
      sosCount: json['sosCount'] as int?,
      memo: json['memo'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'uid': uid,
      'name': name,
      'isLeader': isLeader,
      'stepCount': stepCount,
      'sosCount': sosCount,
      'memo': memo,
    };
  }
}
