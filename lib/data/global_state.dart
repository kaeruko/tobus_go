import '../models/route_models.dart';

// 簡易的なグローバル保存領域 (メモリのみ)
final List<Candidate> kSavedRoutes = [];

// ★追加: 現在参加中のグループID(nullなら一人モード)
String? kCurrentGroupId;

// ★追加: メンバーモードかどうか
bool kIsMemberMode = false;

/// 行き・帰りをまとめて保持する下書き用の簡易モデル。
class TripDraft {
  Candidate? outbound;
  Candidate? inbound;

  bool get isComplete => outbound != null && inbound != null;

  List<Candidate> toRoutes() {
    final list = <Candidate>[];
    if (outbound != null) list.add(outbound!);
    if (inbound != null) list.add(inbound!);
    return list;
  }

  void clear() {
    outbound = null;
    inbound = null;
  }
}

/// アプリ全体で共有する往復の下書き。
final TripDraft kTripDraft = TripDraft();
