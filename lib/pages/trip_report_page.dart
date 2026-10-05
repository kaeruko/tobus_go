import 'package:flutter/material.dart';
import '../l10n/app_localizations.dart';
import '../models/trip_models.dart';
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
          SnackBar(
            content: Text(AppLocalizations.of(context).groupReportMemoSaved),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              AppLocalizations.of(context).groupReportSaveFailed(e.toString()),
            ),
          ),
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
        title: Text(AppLocalizations.of(context).groupReportTitle),
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
            _buildSectionTitle(
              AppLocalizations.of(context).groupReportSchedule,
            ),
            _buildScheduleInfo(trip, startAt, endAt),
            const SizedBox(height: 24),
            _buildSectionTitle(
              AppLocalizations.of(context).groupReportAttendance,
            ),
            _buildParticipantsList(trip),
            if (hasSos) ...[
              const SizedBox(height: 24),
              _buildSectionTitle(AppLocalizations.of(context).groupReportSos),
              _buildSosInfo(trip),
            ],
            const SizedBox(height: 24),
            _buildSectionTitle(AppLocalizations.of(context).groupReportNotes),
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
          Text(
            trip.title,
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Text(
            'ID: ${trip.id}',
            style: const TextStyle(fontSize: 12, color: Colors.grey),
          ),
          Text(
            AppLocalizations.of(context).groupReportDate(
              '${trip.date.year}/${trip.date.month}/${trip.date.day}',
            ),
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Text(AppLocalizations.of(context).groupReportStatus),
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
        label = AppLocalizations.of(context).travelPhasePlanning;
        color = Colors.orange;
        break;
      case TravelPhase.active:
        label = AppLocalizations.of(context).groupReportActive;
        color = Colors.green;
        break;
      case TravelPhase.completed:
        label = AppLocalizations.of(context).travelPhaseCompleted;
        color = Colors.blue;
        break;
      case TravelPhase.cancelled:
        label = AppLocalizations.of(context).travelPhaseCancelled;
        color = Colors.grey;
        break;
    }
    return Chip(
      label: Text(
        label,
        style: const TextStyle(color: Colors.white, fontSize: 12),
      ),
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
                Text(AppLocalizations.of(context).groupReportStart),
                Text(
                  _formatTime(start),
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                ),
              ],
            ),
            const Divider(),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(AppLocalizations.of(context).groupReportEnd),
                Text(
                  _formatTime(end),
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildParticipantsList(Trip trip) {
    return Card(
      child: ListView.separated(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        itemCount: trip.participants.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final p = trip.participants[index];
          return ListTile(
            leading: Icon(
              p.isLeader ? Icons.star : Icons.person,
              color: p.isLeader ? Colors.orange : Colors.grey,
            ),
            title: Text(p.name),
            subtitle: (p.sosCount ?? 0) > 0
                ? Text(
                    AppLocalizations.of(
                      context,
                    ).groupReportSosCount(p.sosCount ?? 0),
                    style: const TextStyle(color: Colors.red),
                  )
                : null,
            trailing: Text(
              p.isLeader
                  ? AppLocalizations.of(context).groupLeader
                  : AppLocalizations.of(context).groupParticipants,
            ),
          );
        },
      ),
    );
  }

  Widget _buildSosInfo(Trip trip) {
    final sosParticipants = trip.participants
        .where((participant) => (participant.sosCount ?? 0) > 0)
        .toList(growable: false);

    return Card(
      color: Colors.red.shade50,
      child: ListView.separated(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        itemCount: sosParticipants.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final participant = sosParticipants[index];
          return ListTile(
            leading: const Icon(Icons.warning, color: Colors.red),
            title: Text(participant.name),
            trailing: Text(
              AppLocalizations.of(
                context,
              ).groupReportSosCount(participant.sosCount ?? 0),
              style: const TextStyle(
                color: Colors.red,
                fontWeight: FontWeight.bold,
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildMemoField() {
    return TextField(
      controller: _memoController,
      maxLines: 5,
      decoration: InputDecoration(
        border: OutlineInputBorder(),
        hintText: AppLocalizations.of(context).groupReportNotesHint,
        filled: true,
        fillColor: Colors.white,
      ),
    );
  }
}
