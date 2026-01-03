import 'package:flutter/material.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../services/trip_service.dart';
import '../utils/string_utils.dart';

class TripReportPage extends StatefulWidget {
  final Trip trip;

  const TripReportPage({super.key, required this.trip});

  @override
  State<TripReportPage> createState() => _TripReportPageState();
}

class _TripReportPageState extends State<TripReportPage> {
  late TextEditingController _memoController;
  final _tripService = TripService();
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    _memoController = TextEditingController(text: widget.trip.staffNotes ?? '');
  }

  @override
  void dispose() {
    _memoController.dispose();
    super.dispose();
  }

  Future<void> _saveMemo() async {
    setState(() => _isSaving = true);
    try {
      await _tripService.updateTripNotes(widget.trip.id, _memoController.text);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('メモを保存しました')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('保存に失敗しました: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isSaving = false);
      }
    }
  }

  String _formatTime(DateTime? dt) {
    if (dt == null) return '--:--';
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  // SOSイベントの集計（本来はTripモデルにイベント履歴があればそれを使うが、今回は簡易的にSOSカウントを表示）
  // ユーザー要望: "SOS発生の有無と内容" -> 現状のモデルでは内容までは持っていない可能性があるため、SOSカウントを表示し、内容フィールドがなければプレースホルダー等の対応が必要。
  // 今回のモデルでは `Participant` に `sosCount` がある。
  // また `TripService.sendSOS` では `alerts` 配列に保存している。Tripモデルには `alerts` がマッピングされていない可能性があるため、
  // Memberを確認する。
  // -> Tripモデルを確認したところ `alerts` フィールドは `Trip` クラスに定義されていない。
  // ですが、`TripService` の `sendSOS` は `alerts` フィールドに書き込んでいる。
  // ここでは `Participant` の `sosCount` を主に使用し、詳細が表示できない場合はその旨を表示する。

  @override
  Widget build(BuildContext context) {
    final trip = widget.trip;
    final startAt = trip.actualDepartureAt ?? trip.plannedDepartureAt;
    
    // スケジュールから終了時間を推定
    DateTime? endAt;
    if (trip.schedule.isNotEmpty) {
      endAt = trip.schedule.last.plannedAt;
    }

    final hasSos = trip.participants.any((p) => (p.sosCount ?? 0) > 0);

    return Scaffold(
      appBar: AppBar(
        title: const Text('実施報告書'),
        actions: [
          IconButton(
            icon: const Icon(Icons.save),
            onPressed: _isSaving ? null : _saveMemo,
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildHeader(trip),
            const SizedBox(height: 24),
            _buildSectionTitle('実施日程と時間'),
            _buildScheduleInfo(trip, startAt, endAt),
            const SizedBox(height: 24),
            _buildSectionTitle('出席者と出欠状況'),
            _buildParticipantsList(trip),
            const SizedBox(height: 24),
            _buildSectionTitle('SOS発生状況'),
            _buildSosInfo(hasSos, trip),
            const SizedBox(height: 24),
            _buildSectionTitle('対応メモ'),
            const SizedBox(height: 8),
            _buildMemoField(),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: const TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.bold,
        color: Colors.blueGrey,
      ),
    );
  }

  Widget _buildHeader(Trip trip) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.blue.shade50,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(trip.title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text('ID: ${trip.id}', style: const TextStyle(fontSize: 12, color: Colors.grey)),
          Text('実施日: ${trip.date.year}/${trip.date.month}/${trip.date.day}'),
          const SizedBox(height: 4),
          Row(
            children: [
              const Text('ステータス: '),
              _buildStatusChip(trip.travelPhase),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatusChip(TravelPhase phase) {
    String label;
    Color color;
    switch (phase) {
      case TravelPhase.planning:
        label = '計画中';
        color = Colors.orange;
        break;
      case TravelPhase.active:
        label = '実施中';
        color = Colors.green;
        break;
      case TravelPhase.completed:
        label = '完了';
        color = Colors.blue;
        break;
      case TravelPhase.cancelled:
        label = '中止';
        color = Colors.grey;
        break;
    }
    return Chip(
      label: Text(label, style: const TextStyle(color: Colors.white, fontSize: 12)),
      backgroundColor: color,
      padding: EdgeInsets.zero,
      visualDensity: VisualDensity.compact,
    );
  }

  Widget _buildScheduleInfo(Trip trip, DateTime? start, DateTime? end) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('開始'),
                Text(_formatTime(start), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              ],
            ),
            const Divider(),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('終了(予定)'),
                Text(_formatTime(end), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildParticipantsList(Trip trip) {
    // ダミーデータを追加して表示（ユーザー要望）
    final displayParticipants = [...trip.participants];
    if (displayParticipants.length < 5) {
      displayParticipants.addAll([
        Participant(uid: 'dummy1', name: '佐藤 花子', isLeader: false, sosCount: 0),
        Participant(uid: 'dummy2', name: '鈴木 一郎', isLeader: false, sosCount: 1),
        Participant(uid: 'dummy3', name: '高橋 次郎', isLeader: false, sosCount: 0),
        Participant(uid: 'dummy4', name: '田中 美咲', isLeader: false, sosCount: 2),
      ]);
    }

    return Card(
      child: ListView.separated(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        itemCount: displayParticipants.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final p = displayParticipants[index];
          return ListTile(
            leading: Icon(p.isLeader ? Icons.star : Icons.person, color: p.isLeader ? Colors.orange : Colors.grey),
            title: Text(p.name),
            subtitle: (p.sosCount ?? 0) > 0 ? Text('SOS回数: ${p.sosCount}', style: const TextStyle(color: Colors.red)) : null,
            trailing: Text(p.isLeader ? 'リーダー' : '参加者'),
          );
        },
      ),
    );
  }

  Widget _buildSosInfo(bool hasSos, Trip trip) {
    // ダミーSOSデータを強制表示（ユーザー要望）
    final dummySosLog = [
      {'name': '鈴木 一郎', 'time': '10:15', 'msg': '転倒により軽傷'},
      {'name': '田中 美咲', 'time': '11:30', 'msg': 'はぐれてしまった'},
      {'name': '田中 美咲', 'time': '11:45', 'msg': '合流完了'},
    ];

    return Card(
      color: Colors.red.shade50,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.warning, color: Colors.red),
                SizedBox(width: 8),
                Text('SOS通知記録 (ダミーデータ)', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 12),
            ...dummySosLog.map((log) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(log['time']!, style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.black54)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(log['name']!, style: const TextStyle(fontWeight: FontWeight.bold)),
                        Text(log['msg']!, style: const TextStyle(color: Colors.black87)),
                      ],
                    ),
                  ),
                ],
              ),
            )),
          ],
        ),
      ),
    );
  }

  Widget _buildMemoField() {
    return TextField(
      controller: _memoController,
      maxLines: 5,
      decoration: const InputDecoration(
        border: OutlineInputBorder(),
        hintText: '特記事項や対応内容を入力してください',
        filled: true,
        fillColor: Colors.white,
      ),
    );
  }
}
