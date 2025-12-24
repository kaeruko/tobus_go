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

    // 0. 進行状況が利用可能な場合、それを使用してアクティブなインデックスを決定する
    if (trip != null && currentStepIndex != null && currentStepIndex >= 0) {
      active = _findActiveIndexByProgress(scheduleSorted, trip, currentStepIndex, nextStopIndex);
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
          active = 0;
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
    if (active != -1 && trip != null && currentStepIndex != null) {
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
  ) {
    debugPrint('[ScheduleResolver] currentStepIndex: $currentStepIndex, nextStopIndex: $nextStopIndex');

    // 1. TripNavigator のロジックに合わせるため、すべてのステップをフラット化する
    var allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();

    // ★追加: ステップが空（ルート未生成など）の場合は「完了」ではなく「判定不能(-1)」を返す
    // 以前は 0 >= 0 で完了扱いになっていた
    if (allSteps.isEmpty) {
      return -1;
    }

    if (currentStepIndex >= allSteps.length) {
      debugPrint('[ScheduleResolver] Completed route. Step $currentStepIndex >= ${allSteps.length}');
      // ルート完了？最後のアナウンス項目（到着/ゴール）を返す
      return schedule.length - 1; 
    }

    // 2. スケジュールを反復処理し、routeStepIndex を使用してステップにマッピングする
    for (int i = 0; i < schedule.length; i++) {
      final entry = schedule[i];
      
      // ★重要: 現在アクティブなLeg (activeLegIndex) に属するエントリーのみを対象とする
      // これにより、物理的に同じ場所にいても「帰り」の予定が先にアクティブになるのを防ぐ
      if (entry.legIndex != trip.activeLegIndex) {
        continue;
      }

      // ルートステップが割り当てられているエントリのみをチェックする
      if (entry.routeStepIndex != null) {
        if (entry.routeStepIndex == currentStepIndex) {
          // インデックスによる一致が見つかった。役割（role）によって洗練させる。
          debugPrint('[ScheduleResolver] Found potential match at index $i (Role: ${entry.routeRole}) for Step $currentStepIndex');
          
          if (entry.routeRole == 'walk') {
            // 徒歩ステップは常に徒歩エントリに一致する
            return i;
          } else if (entry.routeRole == 'ride') {
             // 乗車エントリ。 
             // 以前は remainingStops <= 1 の時に Arrival に切り替えていたが、
             // それだと「次到着します」の赤いナビ画面（Ride状態）が表示されず、
             // いきなり「到着しました」のスケジュール画面（Arrival状態）になってしまう。
             // そのため、ここは最後まで Ride として判定し、TripNavigator 側で「到着」を出すようにする。
             debugPrint('[ScheduleResolver] Ride entry matched. Keeping independent of remaining stops to show Navigation UI.');
             return i;
          } else if (entry.routeRole == 'arrival') {
             // 到着エントリ。
             // Ride が終わって Step が進んだらここに来るはずだが、
             // 同じ StepIndex で複数の Entry (Ride, Arrival) がある場合、
             // 上の Ride で return しているのでここは基本通らない。
             // ただし、もし Ride エントリがない場合はここでマッチする。
             return i;
          }
        }
      }
    }

    return -1;
  }

  static List<ScheduleEntry> sortCopy(List<ScheduleEntry> entries) {
    final copy = [...entries];
    sortScheduleEntries(copy);
    return copy;
  }
}
