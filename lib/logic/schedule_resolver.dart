// lib/logic/schedule_resolver.dart
import 'package:flutter/foundation.dart';
import '../core/app_clock.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';

class ScheduleResolveResult {
  final int activeIndex;
  final String activeLabel;
  final int completedCount;
  final List<ScheduleEntry> window;
  final ScheduleEntry? activeEntry;

  const ScheduleResolveResult({
    required this.activeIndex,
    required this.activeLabel,
    required this.completedCount,
    required this.window,
    required this.activeEntry,
  });
}

class ScheduleResolver {
  static ScheduleResolveResult resolve({
    required List<ScheduleEntry> scheduleSorted,
    required DateTime now,
    Trip? trip,
    int? currentStepIndex,
    int? nextStopIndex,
    int prevCount = 1,
    int nextCount = 3,
    Duration nextThreshold = const Duration(minutes: 20),
  }) {
    int active = -1;
    String label = 'いま';

    // 1. スコアリングによるアクティブ判定 (ユーザー要望のロジック)
    // 時間的な吸着範囲を厳密にして判定する
    active = _resolveActiveIndex(scheduleSorted, now);

    // 判定されなかった場合 (active == -1)
    if (active == -1) {
      if (scheduleSorted.isNotEmpty) {
        final first = scheduleSorted.first;
         // まだ始まっていない未来
        final diff = first.plannedAt.difference(now);
        // 20分以上先なら「そのうち」、それ以内なら「つぎ」
        if (diff.inMinutes > 20) {
           label = 'そのうち';
        } else {
           label = 'つぎ';
        }
      }
    } else {
      label = 'いま';
    }

    final activeEntry = (active >= 0 && active < scheduleSorted.length) ? scheduleSorted[active] : null;

    // 2. 完了数のカウント
    final completedCount = (active >= 0) ? active : 0;

    // 3. ウィンドウ計算
    final start = active >= 0 ? (active - prevCount) : 0;
    final safeStart = start < 0 ? 0 : start;

    final end = active >= 0 ? (active + nextCount) : (nextCount);
    final safeEnd = end >= scheduleSorted.length ? scheduleSorted.length - 1 : end;

    final window = (active >= 0 || scheduleSorted.isNotEmpty) 
        && safeStart <= safeEnd 
        ? scheduleSorted.sublist(safeStart, safeEnd + 1) 
        : <ScheduleEntry>[];

    return ScheduleResolveResult(
      activeIndex: active,
      activeLabel: label,
      completedCount: completedCount,
      window: window,
      activeEntry: activeEntry,
    );
  }

  static int _resolveActiveIndex(List<ScheduleEntry> steps, DateTime now) {
    if (steps.isEmpty) return -1;

    int bestIndex = -1;
    double minScore = 99999.0; 

    for (int i = 0; i < steps.length; i++) {
      final step = steps[i];
      final diffMin = step.plannedAt.difference(now).inMinutes;

      // diffMin > 0 : 未来 (出発前)
      // diffMin < 0 : 過去 (出発後)

      bool isCandidate = false;

      // 吸着判定
      if (step.itemKind == ScheduleEntryKind.ride) {
        // 【修正】乗り物 (Bus/Rail) の場合
        // 「出発5分前 〜 到着予定後(60分)」のみ反応させる
        if (diffMin <= 5 && diffMin > -60) {
          isCandidate = true;
        }
      } else {
        // 徒歩や待機
        if (diffMin <= 10 && diffMin > -20) {
          isCandidate = true;
        }
      }

      if (isCandidate) {
        // 0に近いほど優先（絶対値で比較）
        double score = diffMin.abs().toDouble();
        
        // 既に通過した（マイナス）ステップより、これから（プラス）のステップをやや優先
        // (diffMin < 0 の場合、スコアを少し悪くする = プラスの方が選ばれやすくなる)
        // 例: -2分(score 2.5) vs +2分(score 2) -> +2分が選ばれる = 「これから」を表示
        if (diffMin < 0) score += 0.5; 

        if (score < minScore) {
          minScore = score;
          bestIndex = i;
        }
      }
    }
    
    return bestIndex;
  }

  static int _deriveLegIndexFromGlobalStep(Trip trip, int globalStepIndex) {
    // globalStepIndex がどの leg の step 範囲に入るかを返す
    // legIndex は trip.legs の順番に対応する
    var cursor = 0;
    for (int leg = 0; leg < trip.legs.length; leg++) {
      final count = trip.legs[leg].candidate.steps.length;
      final start = cursor;
      final end = cursor + count;
      if (globalStepIndex >= start && globalStepIndex < end) {
        return leg;
      }
      cursor = end;
    }

    // 範囲外は最後の leg に丸める
    return trip.legs.isEmpty ? 0 : trip.legs.length - 1;
  }

  static List<ScheduleEntry> sortCopy(List<ScheduleEntry> entries) {
    final copy = [...entries];
    sortScheduleEntries(copy);
    return copy;
  }
}
