import 'package:cloud_firestore/cloud_firestore.dart';
import 'route_models.dart';
import 'group_models.dart'; // ScheduleItemを利用

// 旅の状態
enum TripStatus {
  planning,  // 計画中
  active,    // 実施中
  completed, // 完了 (履歴)
}

class Trip {
  final String id;          // FirestoreのDocument ID (6桁コードまたはUUID)
  final String joinCode;    // 参加用6桁コード (検索用)
  final String leaderId;    // 作成者のUID
  final String title;       // 旅のタイトル (例: 上野公園へ遠足)
  final TripStatus status;
  final DateTime date;      // 実施日
  final Candidate route;    // 経路情報
  final List<ScheduleItem> schedule; // しおり
  final List<Participant> participants; // 参加者リスト

  Trip({
    required this.id,
    required this.joinCode,
    required this.leaderId,
    required this.title,
    required this.status,
    required this.date,
    required this.route,
    required this.schedule,
    required this.participants,
  });

  // Firestoreからデータを読み込む時の変換処理
  factory Trip.fromFirestore(DocumentSnapshot doc) {
    final data = doc.data() as Map<String, dynamic>;
    return Trip(
      id: doc.id,
      joinCode: data['joinCode'] ?? '',
      leaderId: data['leaderId'] ?? '',
      title: data['title'] ?? '',
      status: TripStatus.values.firstWhere(
        (e) => e.name == (data['status'] as String?),
        orElse: () => TripStatus.planning,
      ),
      date: (data['date'] as Timestamp).toDate(),
      // 経路情報はネストしたJSONから復元
      route: Candidate.fromJson(data['route'] as Map<String, dynamic>),
      // スケジュール配列の復元
      schedule: (data['schedule'] as List<dynamic>? ?? [])
          .map((e) => ScheduleItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      // 参加者配列の復元
      participants: (data['participants'] as List<dynamic>? ?? [])
          .map((e) => Participant.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }

  // Firestoreに保存する時の変換処理
  Map<String, dynamic> toFirestore() {
    return {
      'joinCode': joinCode,
      'leaderId': leaderId,
      'title': title,
      'status': status.name, // "planning" 等の文字列で保存
      'date': Timestamp.fromDate(date),
      'route': route.toJson(),
      'schedule': schedule.map((e) => e.toJson()).toList(),
      'participants': participants.map((e) => e.toJson()).toList(),
    };
  }
}

// 参加者クラス (メンバー + 実績データ)
class Participant {
  final String uid;       // ユーザーID
  final String name;      // その時の表示名
  final bool isLeader;    // リーダーかどうか
  
  // --- 以下、完了後に埋まる実績データ (一般モードではnull) ---
  final int? stepCount;   // 推定歩数
  final int? sosCount;    // SOS回数
  final String? memo;     // 職員メモ

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
