import 'package:cloud_firestore/cloud_firestore.dart';

import '../logic/group_schedule_shift.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';

class GroupScheduleShiftService {
  final FirebaseFirestore _db;

  GroupScheduleShiftService({FirebaseFirestore? firestore})
      : _db = firestore ?? FirebaseFirestore.instance;

  Future<void> apply({
    required String tripId,
    required String actorUserId,
    required GroupScheduleShiftPlan plan,
  }) async {
    final normalizedTripId = tripId.trim();
    if (normalizedTripId.isEmpty) {
      throw ArgumentError.value(tripId, 'tripId', 'must not be empty');
    }
    final normalizedActorUserId = actorUserId.trim();
    if (normalizedActorUserId.isEmpty) {
      throw ArgumentError.value(
        actorUserId,
        'actorUserId',
        'must not be empty',
      );
    }
    if (plan.targets.isEmpty) {
      throw StateError('グループ予定調整の対象がありません');
    }
    if (plan.shift <= Duration.zero) {
      throw StateError('グループ予定調整量が正ではありません: ${plan.shift}');
    }

    final targetIds = <String>{};
    for (final target in plan.targets) {
      if (!targetIds.add(target.entryId)) {
        throw StateError('グループ予定調整対象IDが重複しています: ${target.entryId}');
      }
      final expectedShifted = target.expectedPlannedAt.add(plan.shift);
      if (!expectedShifted.isAtSameMomentAs(target.shiftedPlannedAt)) {
        throw StateError(
          'グループ予定調整後時刻が計画と一致しません: id=${target.entryId}',
        );
      }
    }
    if (!targetIds.contains(plan.affectedEntryId)) {
      throw StateError(
        '最初の競合予定が調整対象に含まれていません: ${plan.affectedEntryId}',
      );
    }

    final tripRef = _db.collection('trips').doc(normalizedTripId);
    await _db.runTransaction((transaction) async {
      final snapshot = await transaction.get(tripRef);
      if (!snapshot.exists) {
        throw StateError('予定を調整するTripが存在しません: $normalizedTripId');
      }
      final data = snapshot.data();
      if (data == null) {
        throw StateError('予定を調整するTripデータが空です: $normalizedTripId');
      }

      final schemaVersion = data['schemaVersion'] as int?;
      if (schemaVersion != Trip.currentSchemaVersion) {
        throw StateError(
          '予定調整時にTrip schemaが変化しています: '
          'expected=${Trip.currentSchemaVersion}, actual=$schemaVersion',
        );
      }
      final tripTypeName = data['tripType'];
      if (tripTypeName != TripType.group.name) {
        throw StateError('グループ予定の調整対象がgroup Tripではありません: $tripTypeName');
      }
      final phaseName = data['travelPhase'] as String? ?? data['status'] as String?;
      if (phaseName != TravelPhase.active.name) {
        throw StateError('グループ予定の調整対象が移動中ではありません: $phaseName');
      }
      final leaderId = data['leaderId'];
      if (leaderId is! String || leaderId.trim().isEmpty) {
        throw StateError('TripのleaderIdが不正です: $leaderId');
      }
      if (leaderId != normalizedActorUserId) {
        throw StateError('グループ予定を変更できるのはリーダーだけです');
      }

      final rawSchedule = data['schedule'];
      if (rawSchedule is! List) {
        throw StateError('Tripのscheduleが不正です');
      }
      final updatedSchedule = List<dynamic>.from(rawSchedule);

      for (final target in plan.targets) {
        final matchingIndexes = <int>[];
        for (var index = 0; index < updatedSchedule.length; index++) {
          final rawEntry = updatedSchedule[index];
          if (rawEntry is Map && rawEntry['id']?.toString() == target.entryId) {
            matchingIndexes.add(index);
          }
        }
        if (matchingIndexes.length != 1) {
          throw StateError(
            '予定調整対象をFirestore上で一意に特定できません: '
            'id=${target.entryId}, matches=${matchingIndexes.length}',
          );
        }

        final index = matchingIndexes.single;
        final rawEntry = updatedSchedule[index];
        if (rawEntry is! Map) {
          throw StateError('予定調整対象がobjectではありません: ${target.entryId}');
        }
        final entry = Map<String, dynamic>.from(rawEntry);

        if (entry['generatedBy'] != ScheduleEntrySource.manual.name) {
          throw StateError(
            'route生成予定はグループ予定調整で変更できません: ${target.entryId}',
          );
        }
        final legIndex = entry['legIndex'];
        if (legIndex is! int || legIndex != plan.legIndex) {
          throw StateError(
            '予定調整対象のlegが変化しています: '
            'id=${target.entryId}, expected=${plan.legIndex}, actual=$legIndex',
          );
        }
        final plannedAt = entry['plannedAt'];
        if (plannedAt is! Timestamp) {
          throw StateError('予定調整対象のplannedAtが不正です: ${target.entryId}');
        }
        final currentPlannedAt = plannedAt.toDate();
        if (!currentPlannedAt.isAtSameMomentAs(target.expectedPlannedAt)) {
          throw StateError(
            '確認画面を開いた後に予定時刻が変更されました。もう一度確認してください: '
            'id=${target.entryId}',
          );
        }

        entry['plannedAt'] = Timestamp.fromDate(target.shiftedPlannedAt);
        updatedSchedule[index] = entry;
      }

      transaction.update(tripRef, {'schedule': updatedSchedule});
    });
  }
}
