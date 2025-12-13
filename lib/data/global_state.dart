import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../models/route_models.dart';
import '../models/leg_models.dart';

// 簡易的なグローバル保存領域 (メモリのみ)
final List<Candidate> kSavedRoutes = [];

// ★追加: 現在参加中のグループID(nullなら一人モード)
String? kCurrentGroupId;

// ★追加: メンバーモードかどうか
bool kIsMemberMode = false;

/// 行き・帰りをまとめて保持する下書き用の簡易モデル。
class TripDraft {
  final List<LegDraft> legs = [];

  Candidate? get outbound => _candidateFor(LegDirection.outbound);
  Candidate? get inbound => _candidateFor(LegDirection.inbound);

  bool get isComplete {
    final ob = outbound;
    final ib = inbound;
    if (ob == null || ib == null) return false;
    return !_isSameCandidate(ob, ib);
  }

  void setLeg(LegDirection direction, Candidate route) {
    final oppositeDirection =
        direction == LegDirection.outbound ? LegDirection.inbound : LegDirection.outbound;
    final oppositeCandidate = _candidateFor(oppositeDirection);
    if (oppositeCandidate != null && _isSameCandidate(oppositeCandidate, route)) {
      throw StateError('行きと同じ経路は帰りに設定できません');
    }
    final existingIndex = legs.indexWhere((e) => e.direction == direction);
    final newLeg = LegDraft(direction: direction, candidate: route);
    if (existingIndex >= 0) {
      legs[existingIndex] = newLeg;
    } else {
      legs.add(newLeg);
    }
  }

  void clearDirection(LegDirection direction) {
    legs.removeWhere((e) => e.direction == direction);
  }

  List<Leg> toLegs() => legs.map((e) => e.toLeg()).toList();

  bool _isSameCandidate(Candidate a, Candidate b) {
    if (a.id != b.id) return false;
    if (a.points.isEmpty || b.points.isEmpty) return true;
    final sameStart = _isSameLatLng(a.points.first, b.points.first);
    final sameEnd = _isSameLatLng(a.points.last, b.points.last);
    return sameStart && sameEnd;
  }

  bool _isSameLatLng(LatLng a, LatLng b) {
    return a.latitude == b.latitude && a.longitude == b.longitude;
  }

  Candidate? _candidateFor(LegDirection direction) {
    try {
      return legs.firstWhere((e) => e.direction == direction).candidate;
    } catch (_) {
      return null;
    }
  }

  void clear() => legs.clear();
}

/// アプリ全体で共有する往復の下書き。
final TripDraft kTripDraft = TripDraft();
