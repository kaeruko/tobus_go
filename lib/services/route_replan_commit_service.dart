import 'package:cloud_firestore/cloud_firestore.dart';

import '../logic/route_replan_patcher.dart';
import '../models/trip_models.dart';

class RouteReplanCommitService {
  final FirebaseFirestore _db;

  RouteReplanCommitService({FirebaseFirestore? firestore})
      : _db = firestore ?? FirebaseFirestore.instance;

  Future<void> apply({
    required String tripId,
    required RouteReplanPatch patch,
  }) async {
    final normalizedTripId = tripId.trim();
    if (normalizedTripId.isEmpty) {
      throw ArgumentError.value(tripId, 'tripId', 'must not be empty');
    }

    final tripRef = _db.collection('trips').doc(normalizedTripId);
    await _db.runTransaction((transaction) async {
      final snapshot = await transaction.get(tripRef);
      if (!snapshot.exists) {
        throw StateError('再探索を適用するTripが存在しません: $normalizedTripId');
      }
      final data = snapshot.data();
      if (data == null) {
        throw StateError('再探索を適用するTripデータが空です: $normalizedTripId');
      }
      final schemaVersion = data['schemaVersion'] as int?;
      if (schemaVersion != Trip.currentSchemaVersion) {
        throw StateError(
          '再探索適用時にTrip schemaが変化しています: '
          'expected=${Trip.currentSchemaVersion}, actual=$schemaVersion',
        );
      }
      if (data['tripType'] != TripType.solo.name) {
        throw StateError(
          'この再探索適用は一人移動専用です: tripType=${data['tripType']}',
        );
      }
      final phase = data['travelPhase'] as String? ?? data['status'] as String?;
      if (phase != TravelPhase.active.name) {
        throw StateError('移動中ではないTripには再探索を適用できません: phase=$phase');
      }

      final rawLegs = data['legs'];
      if (rawLegs is! List) {
        throw StateError('Tripのlegsが不正です');
      }
      if (patch.legIndex < 0 || patch.legIndex >= rawLegs.length) {
        throw StateError(
          '再探索対象legが現在Tripにありません: legIndex=${patch.legIndex}',
        );
      }
      final rawLeg = rawLegs[patch.legIndex];
      if (rawLeg is! Map) {
        throw StateError('再探索対象legがobjectではありません');
      }
      final rawCandidate = rawLeg['candidate'];
      if (rawCandidate is! Map) {
        throw StateError('再探索対象Candidateがobjectではありません');
      }
      final currentCandidateId = rawCandidate['id']?.toString();
      if (currentCandidateId != patch.expectedCandidateId) {
        throw StateError(
          '比較表示後に経路が更新されました。もう一度経路を見直してください: '
          'expected=${patch.expectedCandidateId}, actual=$currentCandidateId',
        );
      }
      final rawSteps = rawCandidate['steps'];
      if (rawSteps is! List ||
          !rawSteps.any(
            (rawStep) =>
                rawStep is Map &&
                rawStep['step_id']?.toString() == patch.expectedActiveStepId,
          )) {
        throw StateError(
          '比較表示後に現在stepが経路からなくなりました。もう一度経路を見直してください: '
          '${patch.expectedActiveStepId}',
        );
      }

      transaction.update(tripRef, {
        'legs': patch.legs
            .map((leg) => leg.toJson(includePoints: false))
            .toList(),
        'schedule': patch.schedule.map((entry) => entry.toJson()).toList(),
      });
    });
  }
}
