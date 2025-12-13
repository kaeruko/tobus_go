import 'package:flutter/cupertino.dart';
import '../data/global_state.dart';
import '../widgets/route_card.dart';
import 'route_detail_page.dart';
import '../core/api_client.dart';
import '../models/route_models.dart';
import '../widgets/bus_loading_indicator.dart';
import '../services/storage_service.dart';
import '../services/trip_draft_service.dart';
import '../services/trip_service.dart';
import '../models/leg_models.dart';
import 'package:flutter/material.dart'
    show showModalBottomSheet, ListTile, Icons, Colors, Icon, ScaffoldMessenger, SnackBar; // Materialの機能を使うため
import 'package:shared_preferences/shared_preferences.dart';

class MyRoutePage extends StatefulWidget {
  const MyRoutePage({super.key});

  @override
  State<MyRoutePage> createState() => _MyRoutePageState();
}

class _MyRoutePageState extends State<MyRoutePage> {
  DateTime _startTime = DateTime.now();
  bool _loading = false;
  final TripDraftService _draftService = TripDraftService();

  bool _isPlaceholder(String? value) {
    const placeholders = {'出発地', '目的地'};
    if (value == null) return true;
    final trimmed = value.trim();
    return trimmed.isEmpty || placeholders.contains(trimmed);
  }

  String _originLabel(Candidate candidate) {
    if (!_isPlaceholder(candidate.originName)) {
      return candidate.originName!;
    }
    if (candidate.steps.isNotEmpty && !_isPlaceholder(candidate.steps.first.from)) {
      return candidate.steps.first.from!;
    }
    return '出発地';
  }

  String _destinationLabel(Candidate candidate) {
    if (!_isPlaceholder(candidate.destinationName)) {
      return candidate.destinationName!;
    }
    if (candidate.steps.isNotEmpty && !_isPlaceholder(candidate.steps.last.to)) {
      return candidate.steps.last.to!;
    }
    return '目的地';
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // 画面が表示される度にリストを更新
    if (mounted) {
      setState(() {});
    }
  }

  void _showTimePicker() {
    showCupertinoModalPopup(
      context: context,
      builder: (ctx) => Container(
        height: 250,
        color: CupertinoColors.systemBackground,
        child: Column(
          children: [
            SizedBox(
              height: 180,
              child: CupertinoDatePicker(
                mode: CupertinoDatePickerMode.dateAndTime,
                initialDateTime: _startTime,
                use24hFormat: true,
                onDateTimeChanged: (val) {
                  setState(() => _startTime = val);
                },
              ),
            ),
            CupertinoButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('完了'),
            )
          ],
        ),
      ),
    );
  }

  Future<void> _reSearchRoute(Candidate original, {bool reverse = false, bool startReturnFlow = false}) async {
    if (original.points.isEmpty) return;

    setState(() => _loading = true);

    final originLabel = reverse ? _destinationLabel(original) : _originLabel(original);
    final destinationLabel = reverse ? _originLabel(original) : _destinationLabel(original);

    // 簡易的なローディング表示
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
          child: const BusLoadingIndicator(),
        ),
      ),
    );

    try {
      final start = reverse ? original.points.last : original.points.first;
      final end = reverse ? original.points.first : original.points.last;

      print('[DEBUG] MyRoutePage startReturnFlow=$startReturnFlow reverse=$reverse fromDesc=$originLabel toDesc=$destinationLabel fromCoord=${start.latitude},${start.longitude} toCoord=${end.latitude},${end.longitude}');

      final params = {
        'alat': '${start.latitude}',
        'alon': '${start.longitude}',
        'blat': '${end.latitude}',
        'blon': '${end.longitude}',
        'pref': original.preference ?? 'fewTransfers',
        'time': '${_startTime.hour.toString().padLeft(2, '0')}:${_startTime.minute.toString().padLeft(2, '0')}',
        'date': '${_startTime.year}-${_startTime.month.toString().padLeft(2, '0')}-${_startTime.day.toString().padLeft(2, '0')}',
      };

      final j = await ApiClient.post('/route', body: params);
      final jobId = j['job_id']?.toString();
      
      if (jobId == null) throw Exception('Job ID missing');

      // ポーリング開始
      await _poll(
        jobId,
        startReturnFlow: startReturnFlow,
        originLabel: originLabel,
        destinationLabel: destinationLabel,
      );

    } catch (e) {
      if (!mounted) return;
      Navigator.of(context, rootNavigator: true).pop(); // ローディング閉じる
      setState(() => _loading = false);
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('再検索に失敗しました: $e'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            )
          ],
        ),
      );
    }
  }

  Future<void> _poll(
    String jobId, {
    bool startReturnFlow = false,
    required String originLabel,
    required String destinationLabel,
  }) async {
    while (true) {
      await Future.delayed(const Duration(seconds: 1));
      try {
        final j = await ApiClient.get('/route', params: {'job_id': jobId});
        final status = j['status']?.toString();

        if (status == 'done') {
          final result = j['result'];
          final list = (result['candidates'] as List?)?.map((e) {
            final map = Map<String, dynamic>.from(e as Map<String, dynamic>);
            map['origin_name'] = originLabel;
            map['destination_name'] = destinationLabel;
            final candidate = Candidate.fromJson(map);
            final firstStep = candidate.steps.isNotEmpty ? candidate.steps.first : null;
            final lastStep = candidate.steps.isNotEmpty ? candidate.steps.last : null;
            print('[DEBUG] MyRoutePage Parsed candidate originName=${candidate.originName} destinationName=${candidate.destinationName} firstStep.from=${firstStep?.from} lastStep.to=${lastStep?.to}');
            return candidate;
          }).toList();
          RouteMeta? meta;
          final metaJson = result['meta'];
          if (metaJson is Map<String, dynamic>) {
            meta = RouteMeta.fromJson(metaJson);
          }

          if (!mounted) return;
          Navigator.of(context, rootNavigator: true).pop(); // ローディング閉じる
          setState(() => _loading = false);

          if (list != null && list.isNotEmpty) {
            // 最もスコアが良いもの（先頭）を表示、あるいはリスト表示？
            // ここではシンプルに先頭の候補を詳細表示する
            if (!mounted) return;
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
             // 候補なし
             _showError('経路が見つかりませんでした');
          }
          return;
        } else if (status == 'error') {
          throw Exception(j['error']);
        }
        // pending/running -> continue
      } catch (e) {
        rethrow;
      }
    }
  }

  void _showError(String msg) {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        content: Text(msg),
        actions: [
          CupertinoDialogAction(
            child: const Text('OK'),
            onPressed: () => Navigator.pop(ctx),
          )
        ],
      ),
    );
  }

  void _startReturnSearch(Candidate candidate) {
    setState(() {
      _draftService.reset();
      _draftService.setRoute(LegDirection.outbound, candidate);
    });
    _reSearchRoute(candidate, reverse: true, startReturnFlow: true);
  }

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(
        middle: Text('My Route'),
      ),
      child: SafeArea(
        child: Column(
          children: [
            // 日時選択
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: GestureDetector(
                onTap: _showTimePicker,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                  decoration: BoxDecoration(
                    color: CupertinoColors.white,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: CupertinoColors.separator),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('出発日時', style: TextStyle(fontSize: 14)),
                      Text(
                        '${_startTime.month}/${_startTime.day} ${_startTime.hour.toString().padLeft(2, '0')}:${_startTime.minute.toString().padLeft(2, '0')}',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: CupertinoColors.activeBlue,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Expanded(
              child: kSavedRoutes.isEmpty
                  ? const Center(child: Text('保存された経路はありません'))
                  : ListView.separated(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                      itemCount: kSavedRoutes.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 12),
                      itemBuilder: (context, i) {
                        final c = kSavedRoutes[i];
                        return Dismissible(
                          key: Key(c.id + c.points.first.toString() + c.points.last.toString()),
                          direction: DismissDirection.endToStart,
                          confirmDismiss: (direction) async {
                            // 削除確認ダイアログ
                            return await showCupertinoDialog<bool>(
                              context: context,
                              builder: (ctx) => CupertinoAlertDialog(
                                title: const Text('経路を削除'),
                                content: const Text('この経路をMy Routeから削除しますか?'),
                                actions: [
                                  CupertinoDialogAction(
                                    child: const Text('キャンセル'),
                                    onPressed: () => Navigator.pop(ctx, false),
                                  ),
                                  CupertinoDialogAction(
                                    isDestructiveAction: true,
                                    child: const Text('削除'),
                                    onPressed: () => Navigator.pop(ctx, true),
                                  ),
                                ],
                              ),
                            );
                          },
                          onDismissed: (direction) {
                            setState(() {
                              kSavedRoutes.removeAt(i);
                              StorageService().saveRoutes(kSavedRoutes);
                            });
                          },
                          background: Container(
                            alignment: Alignment.centerRight,
                            padding: const EdgeInsets.only(right: 20),
                            decoration: BoxDecoration(
                              color: CupertinoColors.destructiveRed,
                              borderRadius: BorderRadius.circular(16),
                            ),
                            child: const Icon(
                              CupertinoIcons.delete,
                              color: CupertinoColors.white,
                            ),
                          ),
                          child: GestureDetector(
                            // ▼▼▼ 修正箇所ここから ▼▼▼
                            onTap: () {
                              // 再検索(_reSearchRoute)ではなく、直接詳細ページへ遷移します
                              Navigator.of(context).push(
                                CupertinoPageRoute(
                                  builder: (_) => RouteDetailPage(candidate: c),
                                ),
                              );
                            },
                            // ▲▲▲ 修正箇所ここまで ▲▲▲

                            onLongPress: () => _showGroupMenu(context, c),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                RouteCard(candidate: c, rank: i + 1),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }

  void _showGroupMenu(BuildContext context, Candidate route) {
    // 現在グループに参加中（リーダー含む）かどうかチェック
    final isAlreadyInGroup = kCurrentGroupId != null;

    showModalBottomSheet(
      context: context,
      builder: (ctx) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // --- 分岐処理 ---
              if (isAlreadyInGroup)
                ListTile(
                  leading: const Icon(Icons.cancel, color: Colors.red),
                  title: const Text('現在のグループを解散する'),
                  subtitle: const Text('作成中のグループを削除します'),
                  onTap: () async {
                    Navigator.pop(ctx);
                    // 本当に消すか確認ダイアログを出してから実行
                    // ここでは簡易的に直実行しますが、本来は確認推奨
                    try {
                      await TripService().cancelTrip(kCurrentGroupId!);
                      
                      // ローカルの状態もリセット
                      final prefs = await SharedPreferences.getInstance();
                      await prefs.remove('groupId');
                      setState(() {
                        kCurrentGroupId = null; // 画面再描画
                      });
                      
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('グループを解散しました')));
                      }
                    } catch (e) {
                      print(e);
                    }
                  },
                )
              else
                Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    ListTile(
                      leading: Icon(Icons.swap_calls, color: Colors.orange.shade700),
                      title: const Text('帰りを探す（出発地/到着地を入れ替え）'),
                      subtitle: const Text('行きと逆方向で再検索します'),
                      onTap: () {

                        Navigator.pop(ctx);
                        _startReturnSearch(route);
                      },
                    ),
                    ListTile(
                      leading: Icon(Icons.swap_calls, color: Colors.orange.shade700),
                      title: const Text('帰りを探す（出発地/到着地を入れ替え）'),
                      subtitle: const Text('行きと逆方向で再検索します'),
                      onTap: () {
                        Navigator.pop(ctx);
                        _startReturnSearch(route);
                      },
                    ),
                    ListTile(
                      leading: Icon(Icons.refresh, color: Colors.orange.shade700),
                      title: const Text('往復の選択をクリア'),
                      onTap: () {
                        setState(() {
                          _draftService.reset();
                        });
                        Navigator.pop(ctx);
                      },
                    ),
                  ],
                ),
              // ----------------
            ],
          ),
        );
      },
    );
  }
}
