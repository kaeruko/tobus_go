import 'package:cloud_firestore/cloud_firestore.dart';
import 'dart:math';
import '../models/trip_models.dart';
import '../models/group_models.dart'; // ScheduleItemクラス用
import '../models/leg_models.dart';
import 'user_service.dart'; // ユーザーID取得用

class TripService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;
  final UserService _userService = UserService();

  // ---------------------------------------------------
  // 1. 旅を作成する (リーダー用)
  // ---------------------------------------------------
  // 1. 旅を作成する (リーダー用)
  // ---------------------------------------------------
  Future<String> createTrip(List<Leg> legs, List<ScheduleItem> schedule) async {
    print('[DEBUG] TripService.createTrip called');
    final uid = _userService.currentUserId;
    print('[DEBUG] Current UID: $uid');
    final userName = await _userService.getUserName();
    print('[DEBUG] Current UserName: $userName');
    if (uid == null) throw Exception("ユーザーIDが初期化されていません");

    print('[DEBUG] User ID check passed.');

    // 参加コード(6桁)の生成
    final joinCode = (100000 + Random().nextInt(900000)).toString();
    print('[DEBUG] Generated joinCode: $joinCode');

    // リーダーとして自分を参加者リストに追加
    final leader = Participant(
      uid: uid,
      name: userName,
      isLeader: true,
    );
    print('[DEBUG] Created leader participant.');

    // ドキュメントIDはFirestoreに自動生成させる
    final tripRef = _db.collection('trips').doc();
    print('[DEBUG] Generated tripRef ID: ${tripRef.id}');

    // タイトルの自動生成 (行きの目的地を採用)
    final destination =
        (legs.isNotEmpty && legs.first.candidate.steps.isNotEmpty)
            ? legs.first.candidate.steps.last.to
        : "お出かけ";
    final title = "$destination への遠足";
    print('[DEBUG] Generated title: $title');

    final trip = Trip(
      id: tripRef.id,
      joinCode: joinCode,
      leaderId: uid,
      title: title,
      status: TripStatus.planning,
      date: DateTime.now(),
      legs: legs,
      schedule: schedule,
      participants: [leader],
      memberIds: [uid], // リーダーのIDを追加
    );
    print('[DEBUG] Trip object created.');

    try {
      print('[DEBUG] Converting trip to Firestore map...');
      final tripMap = trip.toFirestore();
      print('[DEBUG] key count: ${tripMap.keys.length}');
      
      print('[DEBUG] Saving to Firestore...');
      await tripRef.set(tripMap);
      print('[DEBUG] Saved to Firestore.');
    } catch (e, stack) {
      print('[DEBUG] Error saving to Firestore: $e\n$stack');
      rethrow;
    }
    
    return tripRef.id;
  }

  // ---------------------------------------------------
  // 2. 旅に参加する (メンバー用)
  // ---------------------------------------------------
  Future<String> joinTrip(String joinCode) async {
    final uid = _userService.currentUserId;
    final userName = await _userService.getUserName();
    if (uid == null) throw Exception("ユーザーIDが初期化されていません");

    // joinCode で検索（完了していない旅に限る）
    final snapshot = await _db.collection('trips')
        .where('joinCode', isEqualTo: joinCode)
        .where('status', isNotEqualTo: 'completed') 
        .limit(1)
        .get();

    if (snapshot.docs.isEmpty) {
      throw Exception("見つかりませんでした。コードを確認してください。");
    }

    final tripDoc = snapshot.docs.first;
    final tripId = tripDoc.id;
    
    // 既に参加済みかチェック
    final data = tripDoc.data();
    final participantsRaw = data['participants'] as List<dynamic>? ?? [];
    
    final isAlreadyJoined = participantsRaw.any((p) => p['uid'] == uid);

    if (!isAlreadyJoined) {
      final newMember = Participant(
        uid: uid,
        name: userName,
        isLeader: false,
      );
      
      // Firestoreの配列に追加 (participants と memberIds 両方更新)
      await tripDoc.reference.update({
        'participants': FieldValue.arrayUnion([newMember.toJson()]),
        'memberIds': FieldValue.arrayUnion([uid])
      });
    }

    return tripId; // ドキュメントIDを返す
  }

  // ---------------------------------------------------
  // ★ アクティブな旅を取得する
  // ---------------------------------------------------
  Future<Trip?> getActiveTrip() async {
    final uid = _userService.currentUserId;
    if (uid == null) return null;

    final snapshot = await _db.collection('trips')
        .where('memberIds', arrayContains: uid)
        .where('status', whereIn: ['planning', 'active']) // 計画中か実施中のもの
        .limit(1)
        .get();

    if (snapshot.docs.isNotEmpty) {
      return Trip.fromFirestore(snapshot.docs.first);
    }
    return null;
  }

  // ---------------------------------------------------
  // 3. リアルタイム監視 (共通)
  // ---------------------------------------------------
  Stream<Trip> streamTrip(String tripId) {
    return _db.collection('trips').doc(tripId).snapshots().map((doc) {
      if (!doc.exists) throw Exception("Trip deleted");
      return Trip.fromFirestore(doc);
    });
  }

  // ---------------------------------------------------
  // 4. SOSを送る (メンバー用)
  // ---------------------------------------------------
  Future<void> sendSOS(String tripId) async {
    final uid = _userService.currentUserId;
    
    // NOTE: participants配列の中の自分のデータを更新するのは
    // Firestoreの仕様上少し面倒（配列ごっそり書き換えになる）なので、
    // ここでは簡易的に「SOSコレクション」をサブコレクションとして作るか、
    // あるいは「trip自体にアラートフラグを立てる」実装にします。
    
    // コンテスト向け実装：Tripの 'alerts' フィールドに追記する
    await _db.collection('trips').doc(tripId).update({
      'alerts': FieldValue.arrayUnion([{
        'uid': uid,
        'time': DateTime.now().toIso8601String(),
        'status': 'sos'
      }])
    });
  }

  // ---------------------------------------------------
  // 5. お出かけを開始する (リーダー用)
  // ---------------------------------------------------
  Future<void> startTrip(String tripId) async {
    print('[DEBUG] startTrip called for $tripId'); // ログ推奨
    await _db.collection('trips').doc(tripId).update({
      'status': TripStatus.active.name,
      'startedAt': FieldValue.serverTimestamp(),
    });
  }

  // ---------------------------------------------------
  // 6. お出かけを終了する (リーダー用)
  // ---------------------------------------------------
  Future<void> completeTrip(String tripId) async {
    // ステータスを完了にする
    await _db.collection('trips').doc(tripId).update({
      'status': 'completed',
      'endedAt': FieldValue.serverTimestamp(),
    });
  }

  // グループを解散・中止する (リーダー用)
  Future<void> cancelTrip(String tripId) async {
    await _db.collection('trips').doc(tripId).update({
      'status': 'cancelled',
      'endedAt': FieldValue.serverTimestamp(), // 一応終わった時間は記録
    });
  }

  // ---------------------------------------------------
  // 7. スケジュールを更新する (リーダー用)
  // ---------------------------------------------------
  Future<void> updateSchedule(String tripId, List<ScheduleItem> newSchedule) async {
    // 時間順(Group優先)に並び替えてから保存するのが親切
    newSchedule.sort((a, b) {
      if (a.legIndex != b.legIndex) {
        return a.legIndex.compareTo(b.legIndex);
      }
      return a.time.compareTo(b.time);
    });

    await _db.collection('trips').doc(tripId).update({
      'schedule': newSchedule.map((e) => e.toJson()).toList(),
    });
  }
}