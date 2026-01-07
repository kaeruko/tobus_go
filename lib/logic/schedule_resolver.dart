// lib/logic/schedule_resolver.dart
import 'package:flutter/foundation.dart';
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
  /// スケジュールと現在時刻から、現在の進行状況（アクティブな項目）を解決する。
  /// 
  /// - [scheduleSorted]: 時系列順にソートされた全スケジュールリスト
  /// - [now]: 現在時刻
  /// - [trip]: 旅程データ (未使用、将来用)
  /// - [prevCount]: UI表示用。アクティブ項目の「前」に何件含めるか
  /// - [nextCount]: UI表示用。アクティブ項目の「後」に何件含めるか
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

    // 時間的な吸着範囲を厳密にして判定する
    debugPrint('[ScheduleResolver] resolve start: now=$now entries=${scheduleSorted.length}');
    if (scheduleSorted.isNotEmpty) {
      debugPrint('[ScheduleResolver] schedule head=${scheduleSorted.first.label} at ${scheduleSorted.first.plannedAt}');
      debugPrint('[ScheduleResolver] schedule tail=${scheduleSorted.last.label} at ${scheduleSorted.last.plannedAt}');
    }
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
    debugPrint(
      '[ScheduleResolver] resolved activeIndex=$active label=$label entry='
      '${activeEntry?.label} kind=${activeEntry?.itemKind} plannedAt=${activeEntry?.plannedAt} '
      'routeStepIndex=${activeEntry?.routeStepIndex}',
    );

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

  /// 現在時刻に基づいて、最も「アクティブ」とみなすべきスケジュール項目のインデックスを決定する。
  /// 
  /// **判定ロジック:**
  /// 1. 各スケジュール項目について、現在時刻との差分(分)を計算する。
  /// 2. 項目の種類（乗り物 or その他）に応じて「反応する時間枠（候補ウィンドウ）」を定義し、範囲外なら除外。
  ///    - 乗り物: 出発5分前 〜 出発後60分
  ///    - その他: 開始10分前 〜 開始後20分
  /// 3. 候補に残ったものの中で、最も現在時刻に近い（スコアが低い）ものを選ぶ。
  ///    - 同じような距離なら、少し未来のイベントを優先する（過去のイベントにはペナルティ +0.5）。
  static int _resolveActiveIndex(List<ScheduleEntry> steps, DateTime now) {
    if (steps.isEmpty) return -1;

    int bestIndex = -1;
    double minScore = 99999.0; 

    debugPrint('[ScheduleResolver] Resolving active step at $now (steps=${steps.length})');

    for (int i = 0; i < steps.length; i++) {
      final step = steps[i];
      final diffMin = step.plannedAt.difference(now).inMinutes;

      // diffMin > 0 : 未来 (出発前)
      // diffMin < 0 : 過去 (出発後)

      bool isCandidate = false;

      // 吸着判定
      if (step.itemKind == ScheduleEntryKind.ride) {
        // 【修正】乗り物 (Bus/Rail) の場合
        // 範囲を広げて、ギャップが生じないようにする
        // 120分前(到着後かなり経過) 〜 60分後(出発かなり前) まで候補とする
        if (diffMin <= 60 && diffMin > -120) {
          isCandidate = true;
        }
      } else {
        // 徒歩や待機
        // 長い待機時間なども考慮し、広めに取る
        if (diffMin <= 60 && diffMin > -120) {
          isCandidate = true;
        }
      }

      debugPrint(
        '[ScheduleResolver] Step $i (${step.label}): plannedAt=${step.plannedAt} '
        'diff=${diffMin}m kind=${step.itemKind} candidate=$isCandidate '
        'routeStepIndex=${step.routeStepIndex}',
      );

      if (isCandidate) {
        // 0に近いほど優先（絶対値で比較）
        double score = diffMin.abs().toDouble();
        
        // 既に通過した（マイナス）ステップより、これから（プラス）のステップをやや優先
        // (diffMin < 0 の場合、スコアを少し悪くする = プラスの方が選ばれやすくなる)
        // 例: -2分(score 2.5) vs +2分(score 2) -> +2分が選ばれる = 「これから」を表示
        // 既に通過した（マイナス）ステップより、これから（プラス）のステップをやや優先
        // (diffMin < 0 の場合、スコアを少し悪くする = プラスの方が選ばれやすくなる)
        if (diffMin < 0) score += 0.5;

        // 【追加】もし「乗車」ステップが過去(開始済み)で、次のステップが「到着」かつ未来(未到着)なら、
        // 「乗車中」とみなして、スコアを大幅に良くする（現在のアクティブ項目として優先的に選ばせる）
        if (step.itemKind == ScheduleEntryKind.ride && diffMin < 0) {
           if (i + 1 < steps.length) {
             final next = steps[i + 1];
             if (next.itemKind == ScheduleEntryKind.arrival) {
               final nextDiff = next.plannedAt.difference(now).inMinutes;
               if (nextDiff > 0) { // まだ到着していない
                  // どんなに過去でも「乗車中」なので最優先にする (0.0 or negative to beat others)
                  // 0.1 とかにしておけば、現在時刻ピッタリ(0.0)のイベントがあれば負けるが、
                  // 基本的に到着(nextDiff)よりは小さくなるはず。
                  score = 0.1;
               }
             }
           }
        } 

        debugPrint('  -> Score: $score (best: $minScore)');

        if (score < minScore) {
          minScore = score;
          bestIndex = i;
          debugPrint('[ScheduleResolver] New best -> index=$bestIndex score=$minScore label=${step.label}');
        }
      }
    }
    
    debugPrint('[ScheduleResolver] Selected best index: $bestIndex');
    return bestIndex;
  }


  static List<ScheduleEntry> sortCopy(List<ScheduleEntry> entries) {
    final copy = [...entries];
    sortScheduleEntries(copy);
    return copy;
  }
}
