import 'package:flutter/material.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/route_models.dart'; // StepSeg
import 'trip_navigator.dart';

/// ========================================================================
/// スケジュール解決結果を保持するクラス
/// ========================================================================
/// resolveScheduleState() の戻り値。
/// UIに表示するための「今何をすべきか」を決定した結果を格納する。
class ResolvedScheduleState {
  /// 時刻ベースで「今アクティブ」と判定されたエントリ（未補正）
  final ScheduleEntry? activeEntry;
  
  /// リアルタイム情報等で補正された、最終的に表示すべきエントリ
  final ScheduleEntry? resolvedEntry;
  
  /// 前後のエントリを含むウィンドウ（タイムライン表示用）
  final List<ScheduleEntry> windowEntries;
  
  /// 完了済みのエントリ数
  final int completedCount;
  
  /// 現在の状態ラベル ("いま", "つぎ", "そのうち")
  final String activeLabel;
  
  /// デバッグ用: どのロジックでresolvedが決まったか
  final String resolutionReason;

  const ResolvedScheduleState({
    required this.activeEntry,
    required this.resolvedEntry,
    required this.windowEntries,
    required this.completedCount,
    required this.activeLabel,
    required this.resolutionReason,
  });
}

/// ========================================================================
/// TripCoordinator: 旅程のスケジュール状態を管理するユーティリティクラス
/// ========================================================================
class TripCoordinator {
  
  /// ------------------------------------------------------------------------
  /// ヘルパー: routeStepIndex が設定されていることを保証する
  /// ------------------------------------------------------------------------
  static ScheduleEntry _ensureResolvedEntryHasRouteStepIndex({
    required ScheduleEntry resolvedEntry,
    required void Function(String) addReason,
  }) {
    if (resolvedEntry.routeStepIndex != null) {
      return resolvedEntry;
    }

    addReason("missing_route_step_index");
    assert(() {
      debugPrint(
        "[TripCoordinator] 解決されたエントリにrouteStepIndexがありません: "
        "id=${resolvedEntry.id} label=${resolvedEntry.label}",
      );
      return false;
    }());
    return resolvedEntry;
  }

  /// ------------------------------------------------------------------------
  /// ヘルパー: リアルタイム情報から「乗車が開始されたか」を判定
  /// ------------------------------------------------------------------------
  /// - step.stops の先頭（乗車バス停）にいる、または
  /// - step.stops のどこかにいる場合、乗車中と判断
  static bool _realtimeSaysRideStarted({
    required StepSeg step,
    required String? realtimeBusLocationId,
  }) {
    if (!step.isRide) return false;
    if (realtimeBusLocationId == null) return false;
    if (step.stops.isEmpty) return false;

    final boardingStopId = step.stops.first.stopId;
    final isAtBoarding = boardingStopId != null && realtimeBusLocationId == boardingStopId;
    final isInSegment = step.stops.any((s) => s.stopId == realtimeBusLocationId);

    return isAtBoarding || isInSegment;
  }

  /// ------------------------------------------------------------------------
  /// ヘルパー: ScheduleEntry から対応する StepSeg を取得
  /// ------------------------------------------------------------------------
  static StepSeg? _stepForEntry(RouteState? routeState, ScheduleEntry entry) {
    if (routeState == null) return null;
    final idx = entry.routeStepIndex;
    if (idx == null) return null;
    if (idx < 0) return null;
    if (idx >= routeState.steps.length) return null;
    return routeState.steps[idx];
  }

  /// ========================================================================
  /// メイン関数: スケジュール状態を解決する
  /// ========================================================================
  /// 
  /// 【処理の流れ】
  /// 1. 時刻ベースで「今アクティブなエントリ」を決定 (_resolveActiveIndex)
  /// 2. リアルタイム情報がある場合、到着判定を補正
  /// 3. 最終的な resolvedEntry を決定して返す
  /// 
  /// 【パラメータ】
  /// - scheduleEntries: 全スケジュールエントリ
  /// - now: 現在時刻
  /// - routeState: ルート情報（バス停リスト等）
  /// - realtimeBusLocationId: リアルタイムで取得したバス位置（バス停ID）
  /// - prevCount/nextCount: ウィンドウに含める前後のエントリ数
  /// 
  static ResolvedScheduleState resolveScheduleState({
    required List<ScheduleEntry> scheduleEntries,
    required DateTime now,
    RouteState? routeState,
    String? realtimeBusLocationId,
    int prevCount = 1,
    int nextCount = 3,
  }) {
    // ────────────────────────────────────────────────────────────
    // ステップ1: スケジュールをソートし、時刻ベースでアクティブを判定
    // ────────────────────────────────────────────────────────────
    final scheduleSorted = [...scheduleEntries];
    sortScheduleEntries(scheduleSorted);

    // 時刻だけで判定: 「予定時刻 <= 現在時刻」の最後のエントリを選ぶ
    int activeIndex = _resolveActiveIndex(scheduleSorted, now);
    String activeLabel = 'いま';

    // まだどのエントリも開始していない場合のラベル設定
    if (activeIndex == -1 && scheduleSorted.isNotEmpty) {
      final first = scheduleSorted.first;
      final diff = first.plannedAt.difference(now);
      activeLabel = diff.inMinutes > 20 ? 'そのうち' : 'つぎ';
    }

    // activeIndex が有効なら、そのエントリを取得
    final active = (activeIndex >= 0 && activeIndex < scheduleSorted.length)
        ? scheduleSorted[activeIndex]
        : null;

    // 完了済みカウント = activeIndex（それより前のエントリは全て完了）
    final completedCount = activeIndex >= 0 ? activeIndex : 0;

    // ────────────────────────────────────────────────────────────
    // ステップ2: タイムライン表示用のウィンドウを作成
    // ────────────────────────────────────────────────────────────
    final start = activeIndex >= 0 ? (activeIndex - prevCount) : 0;
    final safeStart = start < 0 ? 0 : start;
    final end = activeIndex >= 0 ? (activeIndex + nextCount) : nextCount;
    final safeEnd = end >= scheduleSorted.length ? scheduleSorted.length - 1 : end;
    final windowEntries = (activeIndex >= 0 || scheduleSorted.isNotEmpty) && safeStart <= safeEnd
        ? scheduleSorted.sublist(safeStart, safeEnd + 1)
        : <ScheduleEntry>[];

    // デバッグ用: どのロジックで決定されたかを記録
    final resolutionReasons = <String>[];
    void addReason(String reason) {
      resolutionReasons.add(reason);
    }

    // ────────────────────────────────────────────────────────────
    // ステップ3: アクティブなエントリがない場合は早期リターン
    // ────────────────────────────────────────────────────────────
    if (active == null) {
      addReason("no_active_entry");
      return ResolvedScheduleState(
        activeEntry: null,
        resolvedEntry: null,
        windowEntries: windowEntries,
        completedCount: completedCount,
        activeLabel: activeLabel,
        resolutionReason: resolutionReasons.join(" | "),
      );
    }

    // ────────────────────────────────────────────────────────────
    // ステップ4: resolved の初期値を active に設定
    // ────────────────────────────────────────────────────────────
    // ここから、リアルタイム情報による補正を行う
    ScheduleEntry resolved = active;
    addReason("active_entry");

    // ────────────────────────────────────────────────────────────
    // ステップ5: 【到着判定の補正】時刻が「到着」でも、実際はまだ乗車中かもしれない
    // ────────────────────────────────────────────────────────────
    // 
    // 【問題】
    // 時刻表上は到着時刻を過ぎているが、バスが遅延していて実際はまだ目的地に着いていない場合、
    // 時刻だけで判定すると「到着」表示になってしまう。
    // 
    // 【解決策】
    // リアルタイムバス位置がある場合、目的地より手前にいるなら「乗車中」に戻す。
    // 
    // 【注意】
    // バスが目的地を通過して次のバス停に移動した場合（ロスト状態）は、
    // currentBusIndex == -1 となり、この補正は適用されない（時刻表の判定を優先）。
    // 
    if (resolved.itemKind == ScheduleEntryKind.arrival && realtimeBusLocationId != null) {
      // この到着エントリに対応する「乗車」エントリを探す（同じ leg 内）
      ScheduleEntry? rideEntry;
      for (final e in scheduleSorted) {
        if (e.legIndex == resolved.legIndex && e.itemKind == ScheduleEntryKind.ride) {
          rideEntry = e;
          break;
        }
      }

      if (rideEntry != null) {
         final rideStep = _stepForEntry(routeState, rideEntry);
         if (rideStep != null && rideStep.stops.isNotEmpty) {
            // 目的地（降車バス停）のIDを取得
            final destStopId = rideStep.stops.last.stopId;
            if (destStopId != null) {
                // バス停リスト内での位置を特定
                int destIndex = -1;      // 目的地のインデックス
                int currentBusIndex = -1; // 現在のバス位置のインデックス
                
                for(int i=0; i<rideStep.stops.length; i++) {
                   if (rideStep.stops[i].stopId == destStopId) destIndex = i;
                   if (rideStep.stops[i].stopId == realtimeBusLocationId) currentBusIndex = i;
                }

                // 【判定ロジック】
                // - 両方見つかった & バスが目的地より手前 → 「乗車中」に戻す
                // - 両方見つかった & バスが目的地以降 → 到着のまま
                // - バス位置が見つからない（-1） → 時刻表の判定を優先（到着のまま）
                //   ※ ロスト状態の可能性があるため、無理に「乗車中」にしない
                
                if (realtimeBusLocationId != destStopId) {
                   if (destIndex != -1 && currentBusIndex != -1) {
                      if (currentBusIndex < destIndex) {
                         // 明確に目的地より手前 → 乗車中に戻す
                         debugPrint("[TripCoordinator] バス位置判定: 目的地より手前 ($currentBusIndex < $destIndex)");
                         resolved = rideEntry;
                         addReason("premature_arrival_revert_index");
                      } else {
                         // 目的地到達または通過済み → 到着のまま
                         debugPrint("[TripCoordinator] バス位置判定: 目的地通過済み ($currentBusIndex >= $destIndex)");
                      }
                   } else {
                      // 位置不明（ロスト等） → 時刻表の判定を信頼
                      debugPrint("[TripCoordinator] バス位置判定: 位置関係不明のため、時刻表の到着判定を優先します (Realtime=$realtimeBusLocationId, Dest=$destStopId)");
                   }
                }
             }
         }
      }
    }

    // ────────────────────────────────────────────────────────────
    // ステップ6: routeStepIndex が設定されていることを確認
    // ────────────────────────────────────────────────────────────

    resolved = _ensureResolvedEntryHasRouteStepIndex(
      resolvedEntry: resolved,
      addReason: addReason,
    );

    // ────────────────────────────────────────────────────────────
    // ステップ7: 完了カウントを補正（resolvedがactiveと異なる場合）
    // ────────────────────────────────────────────────────────────
    final resolvedCompletedCount = _resolveCompletedCount(
      baseCompletedCount: completedCount,
      activeEntry: active,
      resolvedEntry: resolved,
      windowEntries: windowEntries,
    );

    return ResolvedScheduleState(
      activeEntry: active,
      resolvedEntry: resolved,
      windowEntries: windowEntries,
      completedCount: resolvedCompletedCount,
      activeLabel: activeLabel,
      resolutionReason: resolutionReasons.join(" | "),
    );
  }

  /// ------------------------------------------------------------------------
  /// ヘルパー: 完了カウントの補正
  /// ------------------------------------------------------------------------
  /// resolved が active と異なる場合（例: 乗車中に戻された場合）、
  /// タイムライン上での位置差分を反映する。
  static int _resolveCompletedCount({
    required int baseCompletedCount,
    required ScheduleEntry? activeEntry,
    required ScheduleEntry? resolvedEntry,
    required List<ScheduleEntry> windowEntries,
  }) {
    if (activeEntry == null || resolvedEntry == null) {
      return baseCompletedCount;
    }

    if (resolvedEntry.id == activeEntry.id) {
      return baseCompletedCount;
    }

    final activePos = windowEntries.indexWhere((entry) => entry.id == activeEntry.id);
    final resolvedPos = windowEntries.indexWhere((entry) => entry.id == resolvedEntry.id);
    if (activePos == -1 || resolvedPos == -1) {
      return baseCompletedCount;
    }

    final adjusted = baseCompletedCount + (resolvedPos - activePos);
    return adjusted < 0 ? 0 : adjusted;
  }


  static NavigationState buildMemberNavigationState({
    required Trip trip,
    required RouteState? routeState,
    required DateTime now,
    String? realtimeBusLocationId,
    ResolvedScheduleState? resolvedState,
  }) {
    // -------------------------------------------------------------
    // 1. ツアー全体のステータスチェック
    // -------------------------------------------------------------
    // ツアーが終了または中止されている場合は、専用の画面を表示
    if (trip.status == TripStatus.completed) {
      return NavigationState(
        mainText: "終了",
        subText: "お疲れ様でした",
        color: Colors.grey,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "お出かけ終了",
        isMoving: false,
      );
    }
    if (trip.status == TripStatus.cancelled) {
      return NavigationState(
        mainText: "中止",
        subText: "グループは解散されました",
        color: Colors.red,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "中止",
        isMoving: false,
      );
    }

    // 現在のバス停番号（または0）
    final stopIndex = routeState?.nextStopIndex ?? 0;

    if (resolvedState == null || resolvedState.resolvedEntry == null) {
      // 何もない場合は待機状態
      return NavigationState.idle();
    }

    final resolved = resolvedState.resolvedEntry!;
    debugPrint("[TripCoordinator] アクティブ=${resolvedState.activeEntry?.label} 種類=${resolvedState.activeEntry?.itemKind} rt=${resolvedState.activeEntry?.routeStepIndex} リアルタイム=$realtimeBusLocationId");
    debugPrint("[TripCoordinator] 解決済み=${resolved.label} 種類=${resolved.itemKind} rt=${resolved.routeStepIndex}");
    debugPrint("[TripCoordinator] 理由=${resolvedState.resolutionReason}");

    final diff = resolved.plannedAt.difference(now);

    // -------------------------------------------------------------
    // 5. 長時間待機 (20分以上未来) の表示
    // -------------------------------------------------------------
    // かなり先の予定の場合は、詳細なナビではなく「あと◯時間」表示にする
    if (diff.inMinutes > 20) {
      return NavigationState.waitingLong(entry: resolved, diff: diff);
    }

    // -------------------------------------------------------------
    // 6. 最終的なナビゲーション状態の生成
    // -------------------------------------------------------------
    // 決定した resolved エントリーに基づいて、画面表示用オブジェクト(NavigationState)を作成
    final baseState = NavigationState.fromEntry(
      trip: trip,
      entry: resolved,
      step: _stepForEntry(routeState, resolved),
      stopIndex: stopIndex,
      currentStepIndex: routeState?.currentStepIndex ?? 0,
    );

    return baseState;
  }

  static int _resolveActiveIndex(List<ScheduleEntry> steps, DateTime now) {
    if (steps.isEmpty) return -1;

    int bestIndex = -1;
    debugPrint('[TripCoordinator] アクティブステップを解決中 $now (ステップ数=${steps.length})');

    // Simple Time-Range Logic:
    // Select the latest step that has already "started" (plannedAt <= now).
    for (int i = 0; i < steps.length; i++) {
      if (steps[i].plannedAt.isBefore(now) || steps[i].plannedAt.isAtSameMomentAs(now)) {
        bestIndex = i;
      } else {
        // Step is in the future. Since steps are sorted, all subsequent steps are also in future.
        break;
      }
    }
    
    debugPrint('[TripCoordinator] 選択された最良インデックス(TimeRange): $bestIndex');
    return bestIndex;
  }
}
