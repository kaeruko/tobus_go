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

    bool isProgressBased = false;

    // 0. 進行状況が利用可能な場合、それを使用してアクティブなインデックスを決定する
    if (trip != null && currentStepIndex != null && currentStepIndex >= 0) {
      active = _findActiveIndexByProgress(scheduleSorted, trip, currentStepIndex, nextStopIndex, now, nextThreshold);
      if (active != -1) {
        isProgressBased = true;
      }
    }
    
    // 進行状況で一致が見つからなかった場合、または提供されなかった場合は時間ベースにフォールバックする
    if (active == -1) {
      // 1. アクティブなインデックスの決定 (時間ベースの判定)
      final lastPastIndex = scheduleSorted.lastIndexWhere((e) => e.plannedAt.isBefore(now) || e.plannedAt.isAtSameMomentAs(now));

      if (lastPastIndex >= 0) {
        active = lastPastIndex;
        label = 'いま';
      } else {
        // まだ何も始まっていない。すべて未来。
        if (scheduleSorted.isNotEmpty) {
          // active = 0; // 変更: 未来の予定は active=-1 のままにして、開始前状態として扱う
          final diff = scheduleSorted[0].plannedAt.difference(now);
          if (diff > nextThreshold) {
             label = 'そのうち';
          } else {
             label = 'つぎ';
          }
        }
      }
    }

    final activeEntry = (active >= 0 && active < scheduleSorted.length) ? scheduleSorted[active] : null;
    
    // 未来のケースや必要に応じて特定のケースのラベルを洗練させる（進行状況で強制しなかった場合のみ）
    // 実際には、進行状況ベースの一致でも「いま」ラベルで問題ないことが多い。
    if (activeEntry != null) {
      if (activeEntry.plannedAt.isAfter(now)) {
        // 未来のケースだが、進行状況によりアクティブである可能性がある
        // 進行状況によって決定された場合、「いま」や「走行中」を維持したい場合がある。
        // しかし、時間が未来を示している場合は、チェックを継続する。
        final diff = activeEntry.plannedAt.difference(now);
        if (diff > nextThreshold) {
           // 注意: 物理的にそこにいる（進行状況が一致）が、スケジュールが1時間後となっている場合、
           // 進行状況を信頼して labels = 「いま」とすべき。
           // _findActiveIndexByProgress は、そのステップにいる場合にのみ一致を返す。
           // そのため、進行状況で見つかった場合は、基本的にラベルを「走行中」や「いま」で上書きする。
        } else {
           // label = 'つぎ'; // 時間ベースの「次」
        }
      }
    }

    // 進行状況によってアクティブが決定された場合、「いま」（または同様のもの）を強制する
    if (isProgressBased) {
      label = 'いま';
    }

    // 2. 完了数のカウント
    final completedCount = (active >= 0) ? active : (scheduleSorted.isEmpty ? 0 : 0);

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

  /// ルートのステップをスケジュールエントリにマッピングし、どの方のエントリが currentStepIndex に対応するかを見つける
  static int _findActiveIndexByProgress(
    List<ScheduleEntry> schedule, 
    Trip trip, 
    int currentStepIndex,
    int? nextStopIndex,
    DateTime now,
    Duration nextThreshold,
  ) {
    debugPrint('[ScheduleResolver] currentStepIndex: $currentStepIndex, nextStopIndex: $nextStopIndex');

    // 1. TripNavigator のロジックに合わせるため、すべてのステップをフラット化する
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    
    // ★追加: ステップが空（ルート未生成など）の場合は「完了」ではなく「判定不能(-1)」を返す
    // 以前は 0 >= 0 で完了扱いになっていた
    if (allSteps.isEmpty) {
      return -1;
    }

    if (currentStepIndex >= allSteps.length) {
      debugPrint('[ScheduleResolver] Completed route. Step $currentStepIndex >= ${allSteps.length}');
      return schedule.isEmpty ? -1 : schedule.length - 1;
    }

    final activeLegRaw = trip.activeLegIndex;
    final activeLeg = activeLegRaw < 0 ? 0 : (activeLegRaw >= trip.legs.length ? trip.legs.length - 1 : activeLegRaw);
    final derivedLeg = _deriveLegIndexFromGlobalStep(trip, currentStepIndex);

    // activeLeg から乖離しすぎている（2つ以上離れている）場合は、derivedLeg を信用せず activeLeg を基準にする
    // これはGPSの誤検知でいきなり遠くのLegに飛ぶのを防ぐため
    final bool tooFar = (derivedLeg - activeLeg).abs() > 1;
    final int baseLeg = tooFar ? activeLeg : derivedLeg;

    // 基準となるLegと、その次のLegまでを許可範囲とする
    final allowLegA = baseLeg;
    final allowLegB = (baseLeg + 1) < trip.legs.length ? (baseLeg + 1) : baseLeg;

    // derived が allowLegB (つまり次) に進んでいるときは、そこも主対象として扱う
    
    // 2. スケジュールを反復処理し、routeStepIndex を使用してステップにマッピングする
    int bestMatchIndex = -1;
    Duration minTimeDiff = const Duration(days: 999);
    bool foundCurrentOrPast = false;

    for (int i = 0; i < schedule.length; i++) {
      final entry = schedule[i];
      
      // ★重要: 基準Leg (allowLegA) または 次のLeg (allowLegB) に属するエントリーのみ許可する
      final bool legOk = (entry.legIndex == allowLegA) || (entry.legIndex == allowLegB);
      
      if (!legOk) {
        continue;
      }

      // ルートステップが割り当てられているエントリのみをチェックする
      if (entry.routeStepIndex != null) {
        if (entry.routeStepIndex == currentStepIndex) {
          // インデックスによる一致が見つかった。
          
          final diff = entry.plannedAt.difference(now);
          final absDiff = diff.abs();
          
          debugPrint('[ScheduleResolver] Checking match at index $i: plannedAt=${entry.plannedAt}, role=${entry.routeRole}, now=$now, diff=${diff.inMinutes}m');

          // ★Safety Check: 未来すぎる予定はマッチさせない (Step 0 ガード)
          if (entry.plannedAt.isAfter(now)) {
            if (diff > nextThreshold && currentStepIndex == 0) {
              debugPrint('[ScheduleResolver] Ignoring match at index $i (Future: ${diff.inMinutes}m, Step: 0)');
              continue; 
            }
          }

          // ★Time-based Selection Strategy:
          // 同じステップに複数のエントリ(walk, wait, ride...)がある場合、現在時刻に最も近いものを選ぶ。
          // ただし、「すでに時間を過ぎている(past)」ものを優先的に「現在」として扱いたい場合があるが、
          // ここでは単純に「現在時刻との絶対差が最小」のものを選ぶ戦略とする。
          // さらに improvement: もし diff が負(過去) と 正(未来) があるなら、
          // "直近の過去" (いま実行中) を優先すべき。
          
          bool isPast = !entry.plannedAt.isAfter(now);
          
          // 暫定ロジック:
          // 1. まだ Current/Past が見つかっていないなら、無条件で候補にする
          // 2. すでに候補がある場合:
          //    - 今回が Past で、既存が Future なら、今回を優先 (Past > Future)
          //    - 両方 Past なら、より現在に近いほう (diffが0に近い)
          //    - 両方 Future なら、より現在に近いほう
          
          if (bestMatchIndex == -1) {
            bestMatchIndex = i;
            minTimeDiff = absDiff;
            foundCurrentOrPast = isPast;
          } else {
            if (isPast && !foundCurrentOrPast) {
              // Future -> Past への乗り換え (優先度高)
              bestMatchIndex = i;
              minTimeDiff = absDiff;
              foundCurrentOrPast = true;
            } else if (isPast == foundCurrentOrPast) {
              // 同じ属性なら時間が近いほう
              if (absDiff < minTimeDiff) {
                bestMatchIndex = i;
                minTimeDiff = absDiff;
              }
            }
            // 既存が Past で 今回が Future なら更新しない (Keep Past)
          }
        }
      }
    }

    if (bestMatchIndex != -1) {
       final entry = schedule[bestMatchIndex];
       debugPrint('[ScheduleResolver] Selected best match index: $bestMatchIndex (Role: ${entry.routeRole}, Diff: ${minTimeDiff.inMinutes}m)');
       return bestMatchIndex;
    }

    return -1;
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
