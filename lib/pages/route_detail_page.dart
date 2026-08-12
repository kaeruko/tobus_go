import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/app_clock.dart';
import '../models/route_models.dart';
import '../providers/saved_routes_provider.dart';
import '../widgets/timetable_view.dart';
import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../providers/trip_draft_provider.dart';
import '../services/trip_service.dart';
import '../models/trip_models.dart';
import 'leader_mode_page.dart';
import 'group_detail_page.dart';
import 'solo_trip_screen.dart';
import '../core/api_client.dart';
import '../widgets/bus_loading_indicator.dart';
import '../widgets/route_map_preview.dart';
import '../utils/string_utils.dart';

bool _isPlaceholder(String? value) {
  const placeholders = {'出発地', '目的地'};
  if (value == null) return true;
  final trimmed = value.trim();
  return trimmed.isEmpty || placeholders.contains(trimmed);
}

String _originLabelOf(Candidate candidate) {
  if (!_isPlaceholder(candidate.originName)) {
    return candidate.originName!;
  }
  if (candidate.steps.isNotEmpty &&
      !_isPlaceholder(candidate.steps.first.from)) {
    return candidate.steps.first.from!;
  }
  return '出発地';
}

String _destinationLabelOf(Candidate candidate) {
  if (!_isPlaceholder(candidate.destinationName)) {
    return candidate.destinationName!;
  }
  if (candidate.steps.isNotEmpty && !_isPlaceholder(candidate.steps.last.to)) {
    return candidate.steps.last.to!;
  }
  return '目的地';
}

// --- メインの画面 ---
class RouteDetailPage extends ConsumerStatefulWidget {
  final Candidate candidate;
  final bool isReturnSelection;
  final RouteMeta? meta;

  const RouteDetailPage({
    super.key,
    required this.candidate,
    this.isReturnSelection = false,
    this.meta,
  });

  @override
  ConsumerState<RouteDetailPage> createState() => _RouteDetailPageState();
}

class _RouteDetailPageState extends ConsumerState<RouteDetailPage> {
  // 再検索用の日時
  DateTime _searchTime = appClock.now();
  // 帰り検索用の日時 (デフォルトは現在時刻だが、ユーザー操作で変更可能)
  DateTime _returnSearchTime = appClock.now();
  // TripDraftService removed
  final TripService _tripService = TripService(); // 追加

  Trip? _activeTrip; // アクティブな旅の情報
  Trip? _conflictingTrip; // 期間が重複する旅
  bool _isLoadingTrip = true;
  bool _isCreatingSolo = false;

  // 帰り検索フォームの表示フラグ
  bool _isReturnSearchVisible = false;

  bool get _isReturnSelection => widget.isReturnSelection;

  @override
  void initState() {
    super.initState();
    _checkActiveTrip();
  }

  Future<void> _checkActiveTrip() async {
    try {
      final activeTrip = await _tripService.getActiveTrip();
      final futureTrips = await _tripService.getFutureTrips();

      Trip? overlap;

      // お出かけグループ作成直前（帰りの選択中）の場合のみ重複チェックを行う
      if (widget.isReturnSelection) {
        final draft = ref.read(tripDraftProvider);
        final outbound = draft.outbound;

        if (outbound != null && outbound.departureDate != null) {
          final start = outbound.departureDate!;
          // 帰りの到着時刻（または出発+所要時間）を終了時刻とする
          final returnArrival =
              widget.candidate.departureDate?.add(
                Duration(minutes: widget.candidate.totalTime),
              ) ??
              start.add(const Duration(hours: 3)); // フォールバック

          final end = returnArrival;

          // 自分以外のTripとの重複を確認 (activeTripと同じIDなら除外したいが、activeTripは既に別枠で表示されるため、ここでは「active以外」もチェックすべき)
          // ただし _activeTrip != null の場合はUI側でそちらが優先表示されるため、実質的には activeTrip == null のケースで overlap が効く

          for (final trip in futureTrips) {
            // 既に完了・キャンセル済みは除外 (getFutureTripsは planning/active のみ返すはずだが念のため)
            if (trip.status == TripStatus.completed ||
                trip.status == TripStatus.cancelled)
              continue;

            if (_isOverlap(trip, start, end)) {
              overlap = trip;
              break;
            }
          }
        }
      }

      if (mounted) {
        setState(() {
          _activeTrip = activeTrip;
          _conflictingTrip = overlap;
          _isLoadingTrip = false;
        });
      }
    } catch (e) {
      print("Error checking active trip: $e");
      if (mounted) {
        setState(() {
          _isLoadingTrip = false;
        });
      }
    }
  }

  bool _isOverlap(Trip trip, DateTime newStart, DateTime newEnd) {
    final tripStart = trip.plannedDepartureAt ?? trip.date;
    final tripEnd = _getTripEndTime(trip);

    // Overlap logic: (StartA < EndB) and (EndA > StartB)
    return newStart.isBefore(tripEnd) && newEnd.isAfter(tripStart);
  }

  DateTime _getTripEndTime(Trip trip) {
    // スケジュールの最後
    if (trip.schedule.isNotEmpty) {
      // 最後の予定 + 余裕を見て30分?
      // 厳密にはスケジュールのdurationが不明な場合が多いが、plannedAtを基準にする
      final last = trip.schedule
          .map((e) => e.plannedAt)
          .reduce((a, b) => a.isAfter(b) ? a : b);
      return last.add(const Duration(minutes: 60)); // 仮で1時間
    }

    // 経路情報から推測
    if (trip.legs.isNotEmpty) {
      // 最後のLeg
      // LegにはCandidateがあるはず
      // しかしTripモデルのLeg構造を要確認。
      // ここでは簡易的に、出発 + 3時間としておく、もしくは
      // 正確には trip.legs.last.candidate... だがデータ構造が深い
    }

    return (trip.plannedDepartureAt ?? trip.date).add(
      const Duration(hours: 3),
    ); // デフォルト3時間
  }

  // 保存状態の判定ロジック (helper)
  bool _checkIsSaved(List<Candidate> savedRoutes) {
    return savedRoutes.any((e) => _isSameRoute(e, widget.candidate));
  }

  String _originLabel(Candidate candidate) => _originLabelOf(candidate);
  String _destinationLabel(Candidate candidate) =>
      _destinationLabelOf(candidate);

  // 経路が同じか判定するヘルパー
  bool _isSameRoute(Candidate a, Candidate b) {
    if (a.id != b.id) return false;
    if (a.points.isEmpty || b.points.isEmpty) return false;
    final sameStart =
        a.points.first.latitude == b.points.first.latitude &&
        a.points.first.longitude == b.points.first.longitude;
    final sameEnd =
        a.points.last.latitude == b.points.last.latitude &&
        a.points.last.longitude == b.points.last.longitude;
    return sameStart && sameEnd;
  }

  void _toggleBookmark(bool isSaved) {
    if (isSaved) {
      _showDeleteDialog();
    } else {
      ref.read(savedRoutesProvider.notifier).add(widget.candidate);
      _showSavedDialog();
    }
  }

  void _showDeleteDialog() {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('ブックマークを削除'),
        content: const Text('この経路をMy Routeから削除しますか?'),
        actions: [
          CupertinoDialogAction(
            child: const Text('キャンセル'),
            onPressed: () => Navigator.pop(ctx),
          ),
          CupertinoDialogAction(
            isDestructiveAction: true,
            child: const Text('削除'),
            onPressed: () {
              Navigator.pop(ctx);
              ref
                  .read(savedRoutesProvider.notifier)
                  .removeWhere((e) => _isSameRoute(e, widget.candidate));
            },
          ),
        ],
      ),
    );
  }

  void _showSavedDialog() {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('保存しました'),
        content: const Text('My Routeに追加しました。'),
        actions: [
          CupertinoDialogAction(
            child: const Text('OK'),
            onPressed: () => Navigator.pop(ctx),
          ),
        ],
      ),
    );
  }

  void _setDirection(LegDirection direction) {
    try {
      ref
          .read(tripDraftProvider.notifier)
          .setRoute(direction, widget.candidate);
    } on StateError catch (e) {
      _showDuplicateRouteAlert(e.message);
    }
  }

  String _routeLabel(Candidate? candidate) {
    if (candidate == null) return '未選択';
    return candidate.lines.join(' → ');
  }

  void _showDuplicateRouteAlert(String message) {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('別の経路を選択してください'),
        content: Text(message),
        actions: [
          CupertinoDialogAction(
            child: const Text('OK'),
            onPressed: () => Navigator.pop(ctx),
          ),
        ],
      ),
    );
  }

  Widget _roundTripComposer() {
    final draftState = ref.watch(tripDraftProvider);
    final outbound = draftState.outbound;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGroupedBackground,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (_isReturnSelection && outbound != null) ...[
              _selectedOutboundSummary(outbound),
              const SizedBox(height: 12),
            ],
            if (_isReturnSelection) ...[
              if (_isLoadingTrip)
                const Center(child: CupertinoActivityIndicator())
              else if (_activeTrip != null) ...[
                // アクティブな旅がある場合
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: CupertinoColors.activeGreen.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: CupertinoColors.activeGreen),
                  ),
                  child: Column(
                    children: [
                      const Text(
                        "現在進行中のお出かけグループがあります",
                        style: TextStyle(
                          color: CupertinoColors.activeGreen,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      SizedBox(
                        width: double.infinity,
                        child: CupertinoButton.filled(
                          padding: const EdgeInsets.symmetric(vertical: 10),
                          onPressed: () {
                            Navigator.push(
                              context,
                              CupertinoPageRoute(
                                builder: (_) => _activeTrip!.isSolo
                                    ? SoloTripScreen(tripId: _activeTrip!.id)
                                    : GroupDetailPage(trip: _activeTrip!),
                              ),
                            );
                          },
                          child: const Text('お出かけグループ詳細を見る'),
                        ),
                      ),
                    ],
                  ),
                ),
              ] else if (_conflictingTrip != null) ...[
                // ★追加: 期間が重複する旅がある場合
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: CupertinoColors.systemRed.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: CupertinoColors.systemRed),
                  ),
                  child: Column(
                    children: [
                      Text(
                        "期間がかぶるおでかけがあります\n(${_conflictingTrip!.title})",
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: CupertinoColors.systemRed,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      SizedBox(
                        width: double.infinity,
                        child: CupertinoButton(
                          color: CupertinoColors.systemGrey,
                          padding: const EdgeInsets.symmetric(vertical: 10),
                          onPressed: null, // Disabled
                          child: const Text(
                            '作成できません',
                            style: TextStyle(fontWeight: FontWeight.bold),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ] else ...[
                // 通常の作成ボタン
                SizedBox(
                  width: double.infinity,
                  child: CupertinoButton(
                    onPressed: () {
                      _setDirection(LegDirection.inbound);
                      if (ref.read(tripDraftProvider).isComplete) {
                        _showCreateTripDialog();
                      }
                    },
                    child: const Text(
                      'お出かけグループ作成',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        decoration: TextDecoration.underline,
                      ),
                    ),
                  ),
                ),
              ],
            ] else ...[
              // 帰り検索フォーム（初期状態は隠す）
              SizedBox(
                width: double.infinity,
                child: CupertinoButton.filled(
                  onPressed: _isLoadingTrip || _isCreatingSolo
                      ? null
                      : _startSoloTrip,
                  child: Text(
                    _isCreatingSolo ? '移動を準備中…' : 'この経路で行く',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              if (!_isReturnSearchVisible)
                Center(
                  child: CupertinoButton(
                    onPressed: () {
                      setState(() {
                        _isReturnSearchVisible = true;

                        // 帰りの出発時刻の計算:
                        // 1. 行きの「到着時刻」を算出
                        DateTime baseDate =
                            widget.candidate.departureDate ?? appClock.now();
                        // Time component is likely 00:00 in departureDate, so we need to add the time from the last transit step.

                        DateTime? arrivalTime;
                        int trailingWalkMinutes = 0;

                        // 後ろからスキャンして、時刻な有効なステップ(バス/電車)を探す
                        for (final step in widget.candidate.steps.reversed) {
                          if (step.arrivalTime != null &&
                              step.arrivalTime!.contains(':')) {
                            final parts = step.arrivalTime!.split(':');
                            final h = int.parse(parts[0]);
                            final m = int.parse(parts[1]);
                            arrivalTime = DateTime(
                              baseDate.year,
                              baseDate.month,
                              baseDate.day,
                              h,
                              m,
                            );
                            break;
                          } else {
                            // 時刻がないステップ（最後の徒歩など）は時間を加算
                            trailingWalkMinutes += (step.minutes ?? 0);
                          }
                        }

                        if (arrivalTime != null) {
                          // 到着時刻 ＋ 最後の徒歩
                          final finalArrival = arrivalTime.add(
                            Duration(minutes: trailingWalkMinutes),
                          );
                          // 帰りの出発時刻のデフォルトは、行きの到着時刻とする（滞在時間は加算しない）
                          _returnSearchTime = finalArrival;
                        } else {
                          // 時刻が取れない場合は、現在時刻＋(所要時間)等のフォールバック
                          final startTime =
                              widget.candidate.departureDate ?? appClock.now();
                          // Note: departureDate usually doesn't have time, so this might default to midnight if not careful,
                          // but this is a fallback for walk-only paths likely.
                          // Try to use appClock.now() if departureDate is midnight?
                          // For now, simple fallback:
                          if (startTime.hour == 0 && startTime.minute == 0) {
                            _returnSearchTime = appClock.now().add(
                              const Duration(hours: 1),
                            );
                          } else {
                            _returnSearchTime = startTime.add(
                              Duration(minutes: widget.candidate.totalTime),
                            );
                          }
                        }
                      });
                    },
                    padding: const EdgeInsets.symmetric(
                      horizontal: 24,
                      vertical: 12,
                    ),
                    color: CupertinoColors.activeBlue,
                    borderRadius: BorderRadius.circular(24),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          CupertinoIcons.arrow_2_circlepath,
                          color: CupertinoColors.white,
                          size: 20,
                        ),
                        SizedBox(width: 8),
                        Text(
                          '帰りも検索する',
                          style: TextStyle(
                            color: CupertinoColors.white,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ),
                )
              else ...[
                // 閉じるボタンを行の右端に配置
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      '帰りの出発時刻',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                    CupertinoButton(
                      padding: EdgeInsets.zero,
                      minSize: 0,
                      child: const Icon(
                        CupertinoIcons.xmark_circle_fill,
                        color: CupertinoColors.systemGrey,
                      ),
                      onPressed: () {
                        setState(() {
                          _isReturnSearchVisible = false;
                        });
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                // 経路反転の表示
                Container(
                  padding: const EdgeInsets.symmetric(
                    vertical: 8,
                    horizontal: 12,
                  ),
                  decoration: BoxDecoration(
                    color: CupertinoColors.systemGrey6,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        CupertinoIcons.arrow_swap,
                        color: CupertinoColors.systemGrey,
                        size: 16,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          '${_destinationLabel(widget.candidate)} → ${_originLabel(widget.candidate)}',
                          style: const TextStyle(
                            fontWeight: FontWeight.w500,
                            fontSize: 13,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                // 時刻選択行
                GestureDetector(
                  onTap: _showReturnTimePicker,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      vertical: 12,
                      horizontal: 16,
                    ),
                    decoration: BoxDecoration(
                      color: CupertinoColors.systemBackground,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: CupertinoColors.systemGrey4),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          '出発時刻',
                          style: TextStyle(color: CupertinoColors.label),
                        ),
                        Text(
                          '${_returnSearchTime.month}/${_returnSearchTime.day} ${_returnSearchTime.hour.toString().padLeft(2, '0')}:${_returnSearchTime.minute.toString().padLeft(2, '0')}',
                          style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w500,
                            color: CupertinoColors.activeBlue,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: CupertinoButton.filled(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 12,
                    ),
                    onPressed: _startReturnSearch,
                    child: const Text(
                      'この条件で検索',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                  ),
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }

  Widget _selectedOutboundSummary(Candidate candidate) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.systemGrey6,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 4),
          Text(
            candidate.lines.join(' → '),
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          Text(
            '所要時間 ${candidate.totalTime}分・乗換 ${candidate.transfers}回',
            style: const TextStyle(
              fontSize: 12,
              color: CupertinoColors.systemGrey,
            ),
          ),
        ],
      ),
    );
  }

  // --- 再検索機能 (既存維持) ---
  void _showReSearchPicker() {
    _searchTime = appClock.now();
    showCupertinoModalPopup(
      context: context,
      builder: (ctx) => Container(
        height: 280,
        color: CupertinoColors.systemBackground,
        child: Column(
          children: [
            Container(
              alignment: Alignment.centerRight,
              child: CupertinoButton(
                child: const Text('検索実行'),
                onPressed: () {
                  Navigator.pop(ctx);
                  _executeReSearch(startReturnFlow: _isReturnSelection);
                },
              ),
            ),
            SizedBox(
              height: 200,
              child: CupertinoDatePicker(
                mode: CupertinoDatePickerMode.dateAndTime,
                initialDateTime: _searchTime,
                use24hFormat: true,
                onDateTimeChanged: (val) {
                  _searchTime = val;
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  // 置き換え
  Future<void> _showReturnTimePicker() async {
    FocusManager.instance.primaryFocus?.unfocus();
    await Future.delayed(const Duration(milliseconds: 200));

    final baseTime = widget.candidate.departureDate ?? appClock.now();
    final arrivalTime = baseTime.add(
      Duration(minutes: widget.candidate.totalTime),
    );

    if (_returnSearchTime.isBefore(arrivalTime)) {
      _returnSearchTime = arrivalTime;
    }

    if (!mounted) return;

    showCupertinoModalPopup(
      context: context,
      builder: (ctx) => Container(
        height: 280,
        color: CupertinoColors.systemBackground,
        child: Column(
          children: [
            Container(
              alignment: Alignment.centerRight,
              child: CupertinoButton(
                child: const Text('決定'),
                onPressed: () {
                  Navigator.pop(ctx);
                  setState(() {});
                },
              ),
            ),
            SizedBox(
              height: 200,
              child: CupertinoDatePicker(
                mode: CupertinoDatePickerMode.dateAndTime,
                initialDateTime: _returnSearchTime,
                minimumDate: arrivalTime,
                use24hFormat: true,
                onDateTimeChanged: (val) {
                  _returnSearchTime = val;
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _startReturnSearch() async {
    if (widget.candidate.points.length < 2) return;
    if (widget.candidate.points.length < 2) return;

    // Reset and set outbound
    final notifier = ref.read(tripDraftProvider.notifier);
    notifier.reset();
    notifier.setRoute(LegDirection.outbound, widget.candidate);

    // 帰りの検索は _returnSearchTime を使用
    await _executeReSearch(
      reverse: true,
      startReturnFlow: true,
      overrideTime: _returnSearchTime,
    );
  }

  Future<void> _startSoloTrip() async {
    final existing = await _tripService.getActiveTrip();
    if (!mounted) return;
    if (existing != null) {
      await _showActiveTripDialog(existing);
      return;
    }

    setState(() => _isCreatingSolo = true);
    try {
      final tripId = await _tripService.createSoloTrip(widget.candidate);
      if (!mounted) return;
      await Navigator.of(context).push(
        CupertinoPageRoute(builder: (_) => SoloTripScreen(tripId: tripId)),
      );
      await _checkActiveTrip();
    } on ActiveTripExistsException catch (error) {
      final activeTrip = await _tripService.getTrip(error.tripId);
      if (mounted && activeTrip != null) {
        await _showActiveTripDialog(activeTrip);
      }
    } catch (error) {
      if (mounted) {
        showCupertinoDialog(
          context: context,
          builder: (context) => CupertinoAlertDialog(
            title: const Text('移動を開始できませんでした'),
            content: Text('$error'),
            actions: [
              CupertinoDialogAction(
                onPressed: () => Navigator.pop(context),
                child: const Text('閉じる'),
              ),
            ],
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isCreatingSolo = false);
    }
  }

  Future<void> _showActiveTripDialog(Trip trip) {
    return showCupertinoDialog<void>(
      context: context,
      builder: (dialogContext) => CupertinoAlertDialog(
        title: const Text('進行中の移動があります'),
        content: Text('${trip.displayTitle}\n完了または中止してから、新しい移動を開始してください。'),
        actions: [
          CupertinoDialogAction(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('閉じる'),
          ),
          CupertinoDialogAction(
            onPressed: () {
              Navigator.pop(dialogContext);
              if (trip.isSolo) {
                Navigator.of(context).push(
                  CupertinoPageRoute(
                    builder: (_) => SoloTripScreen(tripId: trip.id),
                  ),
                );
              } else {
                Navigator.of(context).push(
                  CupertinoPageRoute(
                    builder: (_) => GroupDetailPage(trip: trip),
                  ),
                );
              }
            },
            child: const Text('進行中の移動を開く'),
          ),
        ],
      ),
    );
  }

  Future<void> _executeReSearch({
    bool reverse = false,
    bool startReturnFlow = false,
    DateTime? overrideTime,
  }) async {
    final original = widget.candidate;
    if (original.points.isEmpty) return;

    final originLabel = reverse
        ? _destinationLabel(original)
        : _originLabel(original);
    final destinationLabel = reverse
        ? _originLabel(original)
        : _destinationLabel(original);

    showCupertinoDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => Center(
        child: Container(
          width: 160,
          height: 160,
          decoration: BoxDecoration(
            color: CupertinoColors.systemBackground,
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              BusLoadingIndicator(),
              SizedBox(height: 16),
              Text('再検索中...', style: TextStyle(fontSize: 14)),
            ],
          ),
        ),
      ),
    );

    try {
      final start = reverse
          ? (original.destinationCoords ?? original.points.last)
          : (original.originCoords ?? original.points.first);
      final end = reverse
          ? (original.originCoords ?? original.points.first)
          : (original.destinationCoords ?? original.points.last);

      print(
        '[DEBUG] startReturnFlow=$startReturnFlow reverse=$reverse fromDesc=$originLabel toDesc=$destinationLabel fromCoord=${start.latitude},${start.longitude} toCoord=${end.latitude},${end.longitude}',
      );

      final targetTime = overrideTime ?? _searchTime;
      final params = {
        'alat': '${start.latitude}',
        'alon': '${start.longitude}',
        'blat': '${end.latitude}',
        'blon': '${end.longitude}',
        'pref': original.preference ?? 'fewTransfers',
        'start_time':
            '${targetTime.hour.toString().padLeft(2, '0')}:${targetTime.minute.toString().padLeft(2, '0')}',
        'target_date_str':
            '${targetTime.year}-${targetTime.month.toString().padLeft(2, '0')}-${targetTime.day.toString().padLeft(2, '0')}',
      };

      // Changed: Await the response synchronously (no job_id polling)
      final result = await ApiClient.post('/route', body: params);

      // Parse result immediately
      final candidatesList = result['candidates'] as List? ?? [];
      final metaMap = result['meta'] as Map<String, dynamic>? ?? {};

      final list = candidatesList.map((e) {
        final map = Map<String, dynamic>.from(e as Map<String, dynamic>);
        map['origin_name'] = originLabel;
        map['destination_name'] = destinationLabel;
        final candidate = Candidate.fromJson(map);
        return candidate;
      }).toList();

      RouteMeta? meta;
      if (metaMap.isNotEmpty) {
        meta = RouteMeta.fromJson(metaMap);
      }

      if (!mounted) return;
      Navigator.of(context, rootNavigator: true).pop(); // Close loading

      if (list.isNotEmpty) {
        // Push new result page
        Navigator.of(context).push(
          CupertinoPageRoute(
            builder: (_) => RouteDetailPage(
              candidate: list.first,
              isReturnSelection: startReturnFlow,
              meta: meta,
            ),
          ),
        );
      } else {
        showCupertinoDialog(
          context: context,
          builder: (ctx) => CupertinoAlertDialog(
            content: const Text('指定された日時の経路が見つかりませんでした。'),
            actions: [
              CupertinoDialogAction(
                child: const Text('OK'),
                onPressed: () => Navigator.pop(ctx),
              ),
            ],
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      Navigator.of(context, rootNavigator: true).pop(); // Close loading
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('再検索に失敗しました: $e'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            ),
          ],
        ),
      );
    }
  }

  // --- お出かけグループ作成機能 (行き・帰りが揃った時だけ表示) ---
  void _showCreateTripDialog() {
    final draftState = ref.read(tripDraftProvider);
    if (!draftState.isComplete) {
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('帰りの経路を選択してください'),
          content: const Text('行きと帰りが揃ってからお出かけグループ作成ができます。'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            ),
          ],
        ),
      );
      return;
    }

    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('この往復でお出かけグループを作成'),
        content: Text(
          '行き: ${_routeLabel(draftState.outbound)}\n帰り: ${_routeLabel(draftState.inbound)}',
        ),
        actions: [
          CupertinoDialogAction(
            child: const Text('キャンセル'),
            onPressed: () => Navigator.pop(ctx),
          ),
          CupertinoDialogAction(
            child: const Text('作成する'),
            onPressed: () {
              Navigator.pop(ctx);
              _createTrip();
            },
          ),
        ],
      ),
    );
  }

  Future<void> _createTrip() async {
    print('[DEBUG] _createTrip called. Widget mounted: $mounted');
    try {
      final tripId = await ref.read(tripDraftProvider.notifier).createTrip();
      print('[DEBUG] Trip created. ID: $tripId');

      if (!mounted) {
        print(
          '[DEBUG] Widget not mounted after createTrip. Aborting navigation.',
        );
        return;
      }

      // 3. リーダー画面へ遷移
      print('[DEBUG] Navigating to LeaderModePage...');
      Navigator.push(
        context,
        CupertinoPageRoute(
          builder: (_) {
            print('[DEBUG] Building LeaderModePage route...');
            return LeaderModePage(tripId: tripId);
          },
        ),
      );
      print('[DEBUG] Navigation pushed.');
    } on ActiveTripExistsException catch (error) {
      final activeTrip = await _tripService.getTrip(error.tripId);
      if (mounted && activeTrip != null) {
        await _showActiveTripDialog(activeTrip);
      }
    } catch (e, stack) {
      print('[DEBUG] Error in _createTrip: $e\n$stack');
      if (!mounted) return;
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('作成に失敗しました: $e'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            ),
          ],
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final savedRoutes = ref.watch(savedRoutesProvider);
    final isSaved = _checkIsSaved(savedRoutes);

    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(widget.candidate.lines.join(' → ')),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 再検索ボタン
            CupertinoButton(
              padding: EdgeInsets.zero,
              onPressed: _showReSearchPicker,
              child: const Icon(CupertinoIcons.clock),
            ),
            // ブックマークボタン
            CupertinoButton(
              padding: EdgeInsets.zero,
              child: Icon(
                isSaved
                    ? CupertinoIcons.bookmark_fill
                    : CupertinoIcons.bookmark,
              ),
              onPressed: () => _toggleBookmark(isSaved),
            ),
          ],
        ),
      ),
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
        child: SafeArea(
          child: CustomScrollView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            slivers: [
              const SliverToBoxAdapter(child: SizedBox(height: 8)),

              if (widget.candidate.isFutureSuggestion)
                SliverToBoxAdapter(
                  child: _FutureSuggestionAlert(
                    date: widget.candidate.departureDate,
                  ),
                ),

              if (widget.meta?.destinationReachable == false)
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16.0),
                    child: _FallbackDestinationNotice(meta: widget.meta!),
                  ),
                ),

              SliverToBoxAdapter(
                child: _EndpointSummary(
                  candidate: widget.candidate,
                  meta: widget.meta,
                ),
              ),

              SliverToBoxAdapter(
                child: RouteSummary(candidate: widget.candidate),
              ),

              const SliverToBoxAdapter(child: SizedBox(height: 12)),

              SliverToBoxAdapter(
                child: RouteMapPreview(points: widget.candidate.points),
              ),

              const SliverToBoxAdapter(child: SizedBox(height: 12)),

              SliverPadding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                sliver: SliverList(
                  delegate: SliverChildBuilderDelegate(
                    (context, index) {
                      final itemIndex = index ~/ 2;
                      if (index.isEven) {
                        return RouteStepTile(
                          segment: widget.candidate.steps[itemIndex],
                        );
                      }
                      return const SizedBox(height: 8);
                    },
                    childCount: widget.candidate.steps.isEmpty
                        ? 0
                        : (widget.candidate.steps.length * 2) - 1,
                  ),
                ),
              ),
              SliverToBoxAdapter(child: _roundTripComposer()),
              const SliverToBoxAdapter(child: SizedBox(height: 48)),
            ],
          ),
        ),
      ),
    );
  }
}

// --- 以下、切り出したWidget群 (別ファイルにしてもOK) ---

class _FutureSuggestionAlert extends StatelessWidget {
  final DateTime? date;
  const _FutureSuggestionAlert({required this.date});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.activeOrange.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: CupertinoColors.activeOrange),
      ),
      child: Row(
        children: [
          const Icon(
            CupertinoIcons.exclamationmark_triangle_fill,
            color: CupertinoColors.activeOrange,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              "ご指定の日時は運行終了または運休日のため、\n${date?.toString().split(' ')[0]} の経路を表示しています。",
              style: const TextStyle(
                color: CupertinoColors.activeOrange,
                fontWeight: FontWeight.bold,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _EndpointSummary extends StatelessWidget {
  final Candidate candidate;
  final RouteMeta? meta;
  const _EndpointSummary({required this.candidate, this.meta});

  String get _origin {
    return StringUtils.extractSimpleName(_originLabelOf(candidate));
  }

  String get _destination {
    if (meta?.destinationReachable == false) {
      final stop = meta?.fallbackNodeName ?? '最寄り停留所';
      final minutes = meta?.fallbackWalkMinutes;
      final suffix = minutes != null ? '（目的地まで徒歩約${minutes}分）' : '';
      return stop + suffix;
    }
    return StringUtils.extractSimpleName(_destinationLabelOf(candidate));
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 6),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _row(CupertinoIcons.location_solid, '出発', _origin),
            const SizedBox(height: 6),
            _row(CupertinoIcons.flag, '目的地', _destination),
          ],
        ),
      ),
    );
  }

  Widget _row(IconData icon, String label, String text) {
    return Row(
      children: [
        Icon(icon, size: 18, color: CupertinoColors.activeBlue),
        const SizedBox(width: 8),
        Text(
          label,
          style: const TextStyle(
            color: CupertinoColors.systemGrey,
            fontSize: 12,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}

class _FallbackDestinationNotice extends StatelessWidget {
  final RouteMeta meta;
  const _FallbackDestinationNotice({required this.meta});

  @override
  Widget build(BuildContext context) {
    final stop = meta.fallbackNodeName ?? '最寄り停留所';
    final minutes = meta.fallbackWalkMinutes;
    final walkText = minutes != null
        ? '徒歩約${minutes}分'
        : (meta.fallbackDistanceM != null
              ? '徒歩${meta.fallbackDistanceM!.toStringAsFixed(0)}m程度'
              : '徒歩圏内');

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.systemYellow.withOpacity(0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: CupertinoColors.systemYellow),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(
                CupertinoIcons.exclamationmark_triangle_fill,
                color: CupertinoColors.systemOrange,
              ),
              SizedBox(width: 8),
              Text(
                '目的地付近までの経路のみ表示しています',
                style: TextStyle(
                  color: CupertinoColors.activeOrange,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '都営だけでは${meta.destinationLabel}に到達できません。最寄りは「$stop」で、ここから$walkTextです。',
            style: const TextStyle(fontSize: 14),
          ),
        ],
      ),
    );
  }
}

class RouteSummary extends StatelessWidget {
  final Candidate candidate;
  const RouteSummary({super.key, required this.candidate});

  String _formatTime(String? timeStr) {
    if (timeStr == null) return '--:--';
    return timeStr;
  }

  String _calcStartTime(String? arrivalStr, int durationMin) {
    if (arrivalStr == null || !arrivalStr.contains(':')) return '--:--';
    try {
      final parts = arrivalStr.split(':');
      final h = int.parse(parts[0]);
      final m = int.parse(parts[1]);
      final arr = DateTime(2020, 1, 1, h, m);
      final start = arr.subtract(Duration(minutes: durationMin));
      return '${start.hour.toString().padLeft(2, '0')}:${start.minute.toString().padLeft(2, '0')}';
    } catch (_) {
      return '--:--';
    }
  }

  @override
  Widget build(BuildContext context) {
    final arr = candidate.arrivalTime;
    final start = _calcStartTime(arr, candidate.totalTime);

    return Column(
      children: [
        // New Time Display Row
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                start,
                style: const TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: CupertinoColors.activeBlue,
                ),
              ),
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 12.0),
                child: Icon(
                  CupertinoIcons.arrow_right,
                  color: CupertinoColors.systemGrey,
                ),
              ),
              Text(
                arr ?? '--:--',
                style: const TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: CupertinoColors.black,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16.0),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _stat('所要時間', '${candidate.totalTime}分'),
              _stat('乗換', candidate.transfers.toString()),
              _stat('乗車区間', candidate.rides.toString()),
              _stat('徒歩', '${candidate.walks}m'),
            ],
          ),
        ),
      ],
    );
  }

  Widget _stat(String k, String v) {
    return Column(
      children: [
        Text(
          v,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 2),
        Text(
          k,
          style: const TextStyle(
            color: CupertinoColors.inactiveGray,
            fontSize: 12,
          ),
        ),
      ],
    );
  }
}

class RouteStepTile extends StatelessWidget {
  final StepSeg segment;
  const RouteStepTile({super.key, required this.segment});

  @override
  Widget build(BuildContext context) {
    final isWalk = segment.kind == 'walk';
    final rightText = _getRightText(isWalk);
    final canShowStops = !isWalk && segment.stops.isNotEmpty;

    final content = Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: CupertinoColors.systemGrey.withValues(alpha: 0.1),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _RoundIcon(kind: segment.kind),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      segment.mainTitle,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    if (segment.departureTime != null &&
                        segment.arrivalTime != null)
                      Text(
                        '${segment.departureTime} → ${segment.arrivalTime}',
                        style: const TextStyle(
                          fontSize: 13,
                          color: CupertinoColors.activeBlue,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    if (segment.subTitle != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        segment.subTitle!,
                        style: const TextStyle(
                          color: CupertinoColors.inactiveGray,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (rightText.isNotEmpty)
                Text(
                  rightText,
                  style: const TextStyle(
                    fontSize: 13,
                    color: CupertinoColors.systemGrey,
                  ),
                ),
            ],
          ),
          if (segment.kind == 'bus' &&
              segment.routeId != null &&
              segment.routeId!.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8.0),
              child: Container(height: 1, color: CupertinoColors.systemGrey5),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4.0),
              child: TimetableView(
                routeId: segment.routeId!,
                stopId: segment.departureStopId,
                targetPoleId: segment.arrivalPoleId, // ターゲット(降車)バス停を渡す
              ),
            ),
          ],
        ],
      ),
    );

    if (!canShowStops) return content;

    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => Navigator.of(context).push(
        CupertinoPageRoute(builder: (_) => SegmentStopsPage(segment: segment)),
      ),
      child: content,
    );
  }

  String _getRightText(bool isWalk) {
    if (segment.minutes != null) return '約${segment.minutes}分';
    if (!isWalk && segment.edges > 0) return '${segment.edges}停';
    if (isWalk && segment.meters != null) return '${segment.meters}m';
    return '';
  }
}

class _RoundIcon extends StatelessWidget {
  final String kind;
  const _RoundIcon({required this.kind});

  @override
  Widget build(BuildContext context) {
    IconData icon;
    Color color;
    switch (kind) {
      case 'walk':
        icon = CupertinoIcons.paw_solid;
        color = CupertinoColors.activeOrange;
        break;
      case 'wait':
        icon = CupertinoIcons.clock;
        color = CupertinoColors.systemGrey;
        break;
      case 'rail':
        icon = CupertinoIcons.tram_fill;
        color = CupertinoColors.systemPurple;
        break;
      default:
        icon = CupertinoIcons.bus;
        color = CupertinoColors.activeBlue;
    }
    return Container(
      width: 36,
      height: 36,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        shape: BoxShape.circle,
      ),
      alignment: Alignment.center,
      child: Icon(icon, color: color),
    );
  }
}

// --- 以下のクラスは別ファイルへ移動推奨だが、今回はここに維持 ---

class SegmentStopsPage extends StatelessWidget {
  final StepSeg segment;
  const SegmentStopsPage({super.key, required this.segment});

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(segment.title.isEmpty ? segment.mainTitle : segment.title),
      ),
      child: SafeArea(
        child: ListView.builder(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          itemCount: segment.stops.length,
          itemBuilder: (context, index) {
            final stop = segment.stops[index];
            final isFirst = index == 0;
            final isLast = index == segment.stops.length - 1;
            return _StopRow(stop: stop, isFirst: isFirst, isLast: isLast);
          },
        ),
      ),
    );
  }
}

class _StopRow extends StatelessWidget {
  final StopPoint stop;
  final bool isFirst;
  final bool isLast;

  const _StopRow({
    required this.stop,
    required this.isFirst,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    final nameStyle = TextStyle(
      fontSize: 16,
      fontWeight: (stop.isOrigin || stop.isDestination)
          ? FontWeight.w600
          : FontWeight.w400,
    );

    return GestureDetector(
      onTap: () {
        if (stop.lat != null && stop.lon != null) {
          Navigator.of(context).push(
            CupertinoPageRoute(builder: (_) => BusStopMapPage(stop: stop)),
          );
        } else {
          print('[DEBUG] lat or lon is null');
        }
      },
      behavior: HitTestBehavior.opaque,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 左側の縦線＋丸
          SizedBox(
            width: 40,
            child: Column(
              children: [
                if (!isFirst)
                  Container(
                    width: 2,
                    height: 12,
                    color: CupertinoColors.systemGrey4,
                  ),
                Container(
                  width: 18,
                  height: 18,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: CupertinoColors.activeGreen,
                      width: 2,
                    ),
                    color: stop.isOrigin || stop.isDestination
                        ? CupertinoColors.activeGreen
                        : CupertinoColors.white,
                  ),
                ),
                if (!isLast)
                  Container(
                    width: 2,
                    height: 24,
                    color: CupertinoColors.systemGrey4,
                  ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          // 右側テキスト
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(stop.name, style: nameStyle),
                  if (stop.isOrigin || stop.isDestination) ...[
                    const SizedBox(height: 2),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 6,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: CupertinoColors.systemGrey5,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        stop.isOrigin ? '乗車' : (stop.isDestination ? '降車' : ''),
                        style: const TextStyle(
                          fontSize: 10,
                          color: CupertinoColors.inactiveGray,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class BusStopMapPage extends StatelessWidget {
  final StopPoint stop;

  const BusStopMapPage({super.key, required this.stop});

  @override
  Widget build(BuildContext context) {
    print(
      '[DEBUG] Viewing map for: ${stop.name}, lat=${stop.lat}, lon=${stop.lon}',
    );
    final target = LatLng(stop.lat ?? 35.681236, stop.lon ?? 139.767125);

    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(middle: Text(stop.name)),
      child: Stack(
        children: [
          GoogleMap(
            initialCameraPosition: CameraPosition(target: target, zoom: 16),
            markers: {
              Marker(
                markerId: MarkerId(stop.name),
                position: target,
                infoWindow: InfoWindow(title: stop.name),
              ),
            },
            myLocationEnabled: true,
            myLocationButtonEnabled: true,
            zoomGesturesEnabled: true,
            scrollGesturesEnabled: true,
            rotateGesturesEnabled: true,
            tiltGesturesEnabled: true,
          ),
          // 下部に住所や情報を出すパネルがあればここに配置
        ],
      ),
    );
  }
}
