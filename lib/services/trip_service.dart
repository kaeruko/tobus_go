import 'package:cloud_firestore/cloud_firestore.dart';
import 'dart:math';
import '../core/app_clock.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/leg_models.dart';
import 'user_service.dart';

class TripService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;
  final UserService _userService = UserService();

  Future<String> createTrip(List<Leg> legs, List<ScheduleEntry> schedule) async {
    final uid = _userService.currentUserId;
    final userName = await _userService.getUserName();
    if (uid == null) throw Exception("ユーザーIDが初期化されていません");

    final joinCode = (100000 + Random().nextInt(900000)).toString();

    final leader = Participant(
      uid: uid,
      name: userName,
      isLeader: true,
    );

    final tripRef = _db.collection('trips').doc();

    String destination = "お出かけ";
    if (legs.isNotEmpty) {
      // LeaderModePageと同じロジック: 行きの便を優先
      final outboundLeg = legs.firstWhere(
        (l) => l.direction == LegDirection.outbound,
        orElse: () => legs.first,
      );
      final c = outboundLeg.candidate;
      
      if (c.destinationName != null &&
          c.destinationName!.isNotEmpty &&
          c.destinationName != '目的地') {
        destination = c.destinationName!;
      } else if (c.steps.isNotEmpty && c.steps.last.to != null) {
        destination = c.steps.last.to!;
      }
    }
    final title = "$destination への遠足";

    sortScheduleEntries(schedule);

    final trip = Trip(
      id: tripRef.id,
      joinCode: joinCode,
      leaderId: uid,
      title: title,
      travelPhase: TravelPhase.planning,
      date: appClock.now(),
      plannedDepartureAt:
          schedule.isNotEmpty ? schedule.first.plannedAt : appClock.now(),
      actualDepartureAt: null,
      legs: legs,
      schedule: schedule,
      participants: [leader],
      memberIds: [uid],
    );

    await tripRef.set(trip.toFirestore());

    return tripRef.id;
  }

  Future<String> joinTrip(String joinCode) async {
    final uid = _userService.currentUserId;
    final userName = await _userService.getUserName();
    if (uid == null) throw Exception("ユーザーIDが初期化されていません");

    final snapshot = await _db
        .collection('trips')
        .where('joinCode', isEqualTo: joinCode)
        .where('travelPhase', isNotEqualTo: TravelPhase.completed.name)
        .limit(1)
        .get();

    if (snapshot.docs.isEmpty) {
      throw Exception("見つかりませんでした。コードを確認してください。");
    }

    final tripDoc = snapshot.docs.first;
    final tripId = tripDoc.id;

    final data = tripDoc.data();
    final participantsRaw = data['participants'] as List<dynamic>? ?? [];

    final isAlreadyJoined = participantsRaw.any((p) => p['uid'] == uid);

    if (!isAlreadyJoined) {
      final newMember = Participant(
        uid: uid,
        name: userName,
        isLeader: false,
      );

      await tripDoc.reference.update({
        'participants': FieldValue.arrayUnion([newMember.toJson()]),
        'memberIds': FieldValue.arrayUnion([uid])
      });
    }

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
          'status': 'sos'
        }
      ])
    });
  }

  Future<void> startTrip(String tripId, DateTime departureTime) async {
    await _db.collection('trips').doc(tripId).update({
      'travelPhase': TravelPhase.active.name,
      'actualDepartureAt': Timestamp.fromDate(departureTime),
      'plannedDepartureAt': FieldValue.delete(),
    });
  }

  Future<void> completeTrip(String tripId) async {
    await _db.collection('trips').doc(tripId).update({
      'travelPhase': TravelPhase.completed.name,
      'endedAt': FieldValue.serverTimestamp(),
    });
  }

  Future<void> cancelTrip(String tripId) async {
    await _db.collection('trips').doc(tripId).update({
      'travelPhase': TravelPhase.cancelled.name,
      'endedAt': FieldValue.serverTimestamp(),
    });
  }

  Future<void> updateSchedule(String tripId, List<ScheduleEntry> newSchedule) async {
    sortScheduleEntries(newSchedule);

    await _db.collection('trips').doc(tripId).update({
      'schedule': newSchedule.map((e) => e.toJson()).toList(),
    });
  }

  List<ScheduleEntry> applyRerouteOutwardOnly(
    List<ScheduleEntry> current,
    List<ScheduleEntry> newOutward,
  ) {
    final retained = current.where((entry) {
      if (entry.legIndex != 0) return true;
      if (entry.locked) return true;
      if (entry.generatedBy != ScheduleEntrySource.route) return true;
      return false;
    }).toList();

    retained.addAll(newOutward
        .where((entry) => entry.legIndex == 0)
        .map((e) => ScheduleEntry(
              plannedAt: e.plannedAt,
              label: e.label,
              description: e.description,
              itemKind: e.itemKind,
              legIndex: 0,
              generatedBy: ScheduleEntrySource.route,
              locked: e.locked,
              isCompleted: false,
            )));

    sortScheduleEntries(retained);

    for (var i = 1; i < retained.length; i++) {
      assert(!retained[i].plannedAt.isBefore(retained[i - 1].plannedAt),
          'Schedule order regressed around ${retained[i].label}');
    }

    // Debug log for cross-day ordering (e.g., 00:00 entries)
    for (final entry in retained) {
      print('[DEBUG] schedule ${entry.legIndex} ${entry.label} at ${entry.plannedAt.toIso8601String()}');
    }

    return retained;
  }

  Future<bool> hasCreatedTrip() async {
    final uid = _userService.currentUserId;
    if (uid == null) return false;

    final snapshot = await _db
        .collection('trips')
        .where('leaderId', isEqualTo: uid)
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

    final snapshot = await _db.collection('trips')
        .where('memberIds', arrayContains: uid)
        .where('travelPhase', whereIn: [TravelPhase.planning.name, TravelPhase.active.name])
        .limit(1)
        .get();

    if (snapshot.docs.isEmpty) return null;
    return Trip.fromFirestore(snapshot.docs.first);
  }

  // 計画中・進行中の全ての旅を取得する（重複チェック用）
  Future<List<Trip>> getFutureTrips() async {
    final uid = _userService.currentUserId;
    if (uid == null) return [];

    final snapshot = await _db.collection('trips')
        .where('memberIds', arrayContains: uid)
        .where('travelPhase', whereIn: [TravelPhase.planning.name, TravelPhase.active.name])
        .get();

    return snapshot.docs.map((d) => Trip.fromFirestore(d)).toList();
  }
}
