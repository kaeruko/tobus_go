import 'package:cloud_firestore/cloud_firestore.dart';
import 'dart:math';
import '../core/app_clock.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../models/route_models.dart';
import '../logic/solo_trip_factory.dart';
import 'user_service.dart';

class ActiveTripExistsException implements Exception {
  final String tripId;

  const ActiveTripExistsException(this.tripId);

  @override
  String toString() => '進行中または計画中の移動があります: $tripId';
}

class TripService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;
  final UserService _userService = UserService();

  Future<String> createTrip(
    List<Leg> legs,
    List<ScheduleEntry> schedule,
  ) async {
    final uid = _userService.currentUserId;
    final userName = await _userService.getUserName();
    if (uid == null) throw Exception("ユーザーIDが初期化されていません");

    final joinCode = (100000 + Random().nextInt(900000)).toString();

    final leader = Participant(uid: uid, name: userName, isLeader: true);

    final tripRef = _db.collection('trips').doc();

    final title = Trip.generateDisplayTitle(legs, "お出かけ への遠足");

    sortScheduleEntries(schedule);

    final trip = Trip(
      id: tripRef.id,
      joinCode: joinCode,
      leaderId: uid,
      title: title,
      travelPhase: TravelPhase.planning,
      date: appClock.now(),
      plannedDepartureAt: schedule.isNotEmpty
          ? schedule.first.plannedAt
          : appClock.now(),
      actualDepartureAt: null,
      legs: legs,
      schedule: schedule,
      participants: [leader],
      memberIds: [uid],
    );

    await _createTripWithClaim(uid: uid, trip: trip, tripRef: tripRef);

    return tripRef.id;
  }

  Future<String> createSoloTrip(Candidate candidate) async {
    final uid = _userService.currentUserId;
    final userName = await _userService.getUserName();
    if (uid == null) throw Exception("ユーザーIDが初期化されていません");

    final tripRef = _db.collection('trips').doc();
    final trip = buildSoloTrip(
      id: tripRef.id,
      userId: uid,
      userName: userName,
      candidate: candidate,
      now: appClock.now(),
    );
    await _createTripWithClaim(uid: uid, trip: trip, tripRef: tripRef);
    return tripRef.id;
  }

  Future<void> _createTripWithClaim({
    required String uid,
    required Trip trip,
    required DocumentReference<Map<String, dynamic>> tripRef,
  }) async {
    final existing = await getActiveTrip();
    if (existing != null) {
      throw ActiveTripExistsException(existing.id);
    }

    final userRef = _db.collection('users').doc(uid);
    await _db.runTransaction((transaction) async {
      final userDoc = await transaction.get(userRef);
      final claimedTripId = userDoc.data()?['activeTripId'] as String?;

      if (claimedTripId != null && claimedTripId.isNotEmpty) {
        final claimedTripRef = _db.collection('trips').doc(claimedTripId);
        final claimedTripDoc = await transaction.get(claimedTripRef);
        final claimedData = claimedTripDoc.data();
        if (claimedTripDoc.exists && _isActiveTripData(claimedData)) {
          throw ActiveTripExistsException(claimedTripId);
        }
      }

      transaction.set(tripRef, trip.toFirestore());
      transaction.set(userRef, {
        'activeTripId': tripRef.id,
      }, SetOptions(merge: true));
    });
  }

  bool _isActiveTripData(Map<String, dynamic>? data) {
    final phase = data?['travelPhase'] as String? ?? data?['status'] as String?;
    return phase == TravelPhase.planning.name ||
        phase == TravelPhase.active.name;
  }

  Future<String> joinTrip(String joinCode) async {
    final uid = _userService.currentUserId;
    final userName = await _userService.getUserName();
    if (uid == null) throw Exception("ユーザーIDが初期化されていません");
    if (joinCode.trim().isEmpty) throw ArgumentError('参加コードを入力してください');

    final snapshot = await _db
        .collection('trips')
        .where('joinCode', isEqualTo: joinCode)
        .limit(1)
        .get();

    if (snapshot.docs.isEmpty) {
      throw Exception("見つかりませんでした。コードを確認してください。");
    }

    final tripDoc = snapshot.docs.first;
    final tripId = tripDoc.id;

    final data = tripDoc.data();
    final schemaVersion = data['schemaVersion'] as int?;
    if (schemaVersion != Trip.currentSchemaVersion) {
      throw StateError('旧形式のおでかけです。作り直してください。');
    }
    final phase = data['travelPhase'] as String? ?? data['status'] as String?;
    if (phase == TravelPhase.completed.name ||
        phase == TravelPhase.cancelled.name) {
      throw StateError('このおでかけには参加できません。');
    }
    final existing = await getActiveTrip();
    if (existing != null && existing.id != tripId) {
      throw ActiveTripExistsException(existing.id);
    }

    final userRef = _db.collection('users').doc(uid);
    await _db.runTransaction((transaction) async {
      final userDoc = await transaction.get(userRef);
      final targetDoc = await transaction.get(tripDoc.reference);
      if (!targetDoc.exists) throw StateError('このおでかけは存在しません。');

      final claimedTripId = userDoc.data()?['activeTripId'] as String?;
      if (claimedTripId != null &&
          claimedTripId.isNotEmpty &&
          claimedTripId != tripId) {
        final claimedDoc = await transaction.get(
          _db.collection('trips').doc(claimedTripId),
        );
        if (claimedDoc.exists && _isActiveTripData(claimedDoc.data())) {
          throw ActiveTripExistsException(claimedTripId);
        }
      }

      final targetData = targetDoc.data()!;
      if (targetData['tripType'] == TripType.solo.name) {
        throw StateError('一人用の移動には参加できません。');
      }
      if (!_isActiveTripData(targetData)) {
        throw StateError('このおでかけには参加できません。');
      }
      final participantsRaw =
          targetData['participants'] as List<dynamic>? ?? [];
      final isAlreadyJoined = participantsRaw.any(
        (participant) => participant['uid'] == uid,
      );
      if (!isAlreadyJoined) {
        final newMember = Participant(
          uid: uid,
          name: userName,
          isLeader: false,
        );
        transaction.update(tripDoc.reference, {
          'participants': FieldValue.arrayUnion([newMember.toJson()]),
          'memberIds': FieldValue.arrayUnion([uid]),
        });
      }
      transaction.set(userRef, {
        'activeTripId': tripId,
      }, SetOptions(merge: true));
    });

    return tripId;
  }

  Stream<Trip> streamTrip(String tripId) {
    return _db.collection('trips').doc(tripId).snapshots().map((doc) {
      if (!doc.exists) throw Exception("Trip deleted");
      return Trip.fromFirestore(doc);
    });
  }

  Future<void> sendSOS(String tripId) async {
    final uid = _userService.currentUserId;

    await _db.collection('trips').doc(tripId).update({
      'alerts': FieldValue.arrayUnion([
        {
          'uid': uid,
          'sentAt': appClock.now().toIso8601String(),
          'status': 'sos',
        },
      ]),
    });
  }

  Future<void> startTrip(String tripId, DateTime departureTime) async {
    await _db.collection('trips').doc(tripId).update({
      'travelPhase': TravelPhase.active.name,
      'status': TravelPhase.active.name,
      'actualDepartureAt': Timestamp.fromDate(departureTime),
      'plannedDepartureAt': FieldValue.delete(),
    });
  }

  Future<void> completeTrip(String tripId) async {
    await _finishTrip(tripId, TravelPhase.completed);
  }

  Future<void> cancelTrip(String tripId) async {
    await _finishTrip(tripId, TravelPhase.cancelled);
  }

  Future<void> _finishTrip(String tripId, TravelPhase phase) async {
    final tripRef = _db.collection('trips').doc(tripId);
    final uid = _userService.currentUserId;
    if (uid == null) {
      await tripRef.update({
        'travelPhase': phase.name,
        'status': phase.name,
        'endedAt': FieldValue.serverTimestamp(),
      });
      return;
    }

    final userRef = _db.collection('users').doc(uid);
    await _db.runTransaction((transaction) async {
      final userDoc = await transaction.get(userRef);
      transaction.update(tripRef, {
        'travelPhase': phase.name,
        'status': phase.name,
        'endedAt': FieldValue.serverTimestamp(),
      });
      if (userDoc.data()?['activeTripId'] == tripId) {
        transaction.set(userRef, {
          'activeTripId': FieldValue.delete(),
        }, SetOptions(merge: true));
      }
    });
  }

  Future<void> updateSchedule(
    String tripId,
    List<ScheduleEntry> newSchedule,
  ) async {
    sortScheduleEntries(newSchedule);

    await _db.collection('trips').doc(tripId).update({
      'schedule': newSchedule.map((e) => e.toJson()).toList(),
    });
  }

  Future<void> updateCompletedLegIndex(String tripId, int index) async {
    await _db.collection('trips').doc(tripId).update({
      'completedLegIndex': index,
    });
  }

  List<ScheduleEntry> applyRerouteOutwardOnly(
    List<ScheduleEntry> current,
    List<ScheduleEntry> newOutward,
  ) {
    final retained = current.where((entry) {
      if (entry.legIndex != 0) return true;
      if (entry.generatedBy != ScheduleEntrySource.route) return true;
      return false;
    }).toList();

    retained.addAll(
      newOutward
          .where((entry) => entry.legIndex == 0)
          .map(
            (e) => ScheduleEntry(
              plannedAt: e.plannedAt,
              label: e.label,
              description: e.description,
              itemKind: e.itemKind,
              legIndex: 0,
              generatedBy: ScheduleEntrySource.route,
              routeStepId: e.routeStepId,
              routeRole: e.routeRole,
            ),
          ),
    );

    sortScheduleEntries(retained);

    for (var i = 1; i < retained.length; i++) {
      assert(
        !retained[i].plannedAt.isBefore(retained[i - 1].plannedAt),
        'Schedule order regressed around ${retained[i].label}',
      );
    }

    // Debug log for cross-day ordering (e.g., 00:00 entries)
    for (final entry in retained) {
      print(
        '[DEBUG] schedule ${entry.legIndex} ${entry.label} at ${entry.plannedAt.toIso8601String()}',
      );
    }

    return retained;
  }

  Future<bool> hasCreatedTrip() async {
    final uid = _userService.currentUserId;
    if (uid == null) return false;

    final snapshot = await _db
        .collection('trips')
        .where('leaderId', isEqualTo: uid)
        .where('schemaVersion', isEqualTo: Trip.currentSchemaVersion)
        .limit(1)
        .get();

    return snapshot.docs.isNotEmpty;
  }

  Future<List<Trip>> getCompletedTrips() async {
    final uid = _userService.currentUserId;
    if (uid == null) return [];

    final snapshot = await _db
        .collection('trips')
        .where('memberIds', arrayContains: uid)
        .where('travelPhase', isEqualTo: TravelPhase.completed.name)
        .get();

    final trips = snapshot.docs.map((doc) => Trip.fromFirestore(doc)).toList();

    trips.sort((a, b) => b.date.compareTo(a.date));

    return trips;
  }

  // アクティブ（計画中または移動中）な旅を取得する
  Future<Trip?> getActiveTrip() async {
    final uid = _userService.currentUserId;
    if (uid == null) return null;

    final snapshot = await _db
        .collection('trips')
        .where('memberIds', arrayContains: uid)
        .where(
          'travelPhase',
          whereIn: [TravelPhase.planning.name, TravelPhase.active.name],
        )
        .limit(1)
        .get();

    if (snapshot.docs.isEmpty) return null;
    return Trip.fromFirestore(snapshot.docs.first);
  }

  // 計画中・進行中の全てのおでかけを取得する（重複チェック用）
  Future<List<Trip>> getFutureTrips() async {
    final uid = _userService.currentUserId;
    if (uid == null) return [];

    final snapshot = await _db
        .collection('trips')
        .where('memberIds', arrayContains: uid)
        .where(
          'travelPhase',
          whereIn: [TravelPhase.planning.name, TravelPhase.active.name],
        )
        .get();

    return snapshot.docs.map((d) => Trip.fromFirestore(d)).toList();
  }

  // 追加: ユーザーが関わる全てのTripを取得（日付降順）
  Future<List<Trip>> getAllTrips() async {
    final uid = _userService.currentUserId;
    if (uid == null) return [];

    final snapshot = await _db
        .collection('trips')
        .where('memberIds', arrayContains: uid)
        .get();

    // navigation v2以前のデータは現在のTripとして復元できないため、
    // 一覧全体をエラーにせず履歴から除外する。
    final trips = snapshot.docs
        .where((d) => d.data()['schemaVersion'] == Trip.currentSchemaVersion)
        .map((d) => Trip.fromFirestore(d))
        .toList();
    // メモリ内でソート（Firestoreの複合インデックス作成回避のため）
    trips.sort((a, b) => b.date.compareTo(a.date));
    return trips;
  }

  // 追加: スタッフメモを更新
  Future<void> updateTripNotes(String tripId, String notes) async {
    await _db.collection('trips').doc(tripId).update({'staffNotes': notes});
  }

  Stream<Trip?> streamActiveTrip() {
    final uid = _userService.currentUserId;
    if (uid == null) return Stream.value(null);

    final q = _db
        .collection('trips')
        .where('memberIds', arrayContains: uid)
        .where(
          'travelPhase',
          whereIn: [TravelPhase.planning.name, TravelPhase.active.name],
        )
        .limit(1);

    return q.snapshots().map((snap) {
      if (snap.docs.isEmpty) return null;
      return Trip.fromFirestore(snap.docs.first);
    });
  }

  Future<void> updateTripScheduleWithNewReturnTime(
    String tripId,
    DateTime newReturnTime,
  ) async {
    final doc = await _db.collection('trips').doc(tripId).get();
    if (!doc.exists) throw Exception("Trip not found");
    final trip = Trip.fromFirestore(doc);

    final newSchedule = createScheduleFromLegs(
      trip.legs,
      userSelectedReturnTime: newReturnTime,
    );

    await updateSchedule(tripId, newSchedule);
  }

  Future<Trip?> getTrip(String tripId) async {
    final doc = await _db.collection('trips').doc(tripId).get();
    if (!doc.exists) return null;
    return Trip.fromFirestore(doc);
  }
}
