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

  bool get isComplete => outbound != null && inbound != null;

  void setLeg(LegDirection direction, Candidate route) {
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
