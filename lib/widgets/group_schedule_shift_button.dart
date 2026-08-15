import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/group_schedule_impact.dart';
import '../logic/group_schedule_shift.dart';
import '../models/trip_models.dart';
import '../providers/group_schedule_impact_provider.dart';
import '../services/group_schedule_shift_service.dart';
import '../services/user_service.dart';

class GroupScheduleShiftButton extends ConsumerStatefulWidget {
  final Trip trip;
  final GroupScheduleImpact impact;

  const GroupScheduleShiftButton({
    super.key,
    required this.trip,
    required this.impact,
  });

  @override
  ConsumerState<GroupScheduleShiftButton> createState() =>
      _GroupScheduleShiftButtonState();
}

class _GroupScheduleShiftButtonState
    extends ConsumerState<GroupScheduleShiftButton> {
  bool _loading = false;

  @override
  Widget build(BuildContext context) {
    final minutes = _ceilMinutes(widget.impact.overrun);
    return OutlinedButton.icon(
      onPressed: _loading ? null : _openConfirmation,
      icon: _loading
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.update),
      label: Text(_loading ? '予定を更新中…' : 'グループ予定を+$minutes分ずらす'),
    );
  }

  Future<void> _openConfirmation() async {
    if (_loading) return;

    GroupScheduleShiftPlan plan;
    try {
      plan = GroupScheduleShiftPlanner.build(
        trip: widget.trip,
        impact: widget.impact,
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('予定調整を準備できませんでした: $error')),
      );
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('この予定以降を${plan.shiftMinutes}分ずらしますか？'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final target in plan.targets) ...[
                Text(
                  '${target.label}\n'
                  '${_clock(target.expectedPlannedAt)} → '
                  '${_clock(target.shiftedPlannedAt)}',
                ),
                const SizedBox(height: 10),
              ],
              const Text(
                '電車・バスなど経路由来の予定と、別legの帰りの経路は変更しません。',
                style: TextStyle(color: Colors.black54, fontSize: 13),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('キャンセル'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text('${plan.shiftMinutes}分ずらす'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final latestImpact = ref.read(groupScheduleImpactProvider);
    if (latestImpact == null || !_sameImpact(latestImpact, widget.impact)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('到着見込みが変わりました。最新の警告内容を確認して、もう一度調整してください。'),
        ),
      );
      return;
    }

    final actorUserId = UserService().currentUserId;
    if (actorUserId == null || actorUserId.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('予定を変更するユーザーIDを取得できません')),
      );
      return;
    }

    setState(() => _loading = true);
    try {
      await GroupScheduleShiftService().apply(
        tripId: widget.trip.id,
        actorUserId: actorUserId,
        plan: plan,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('グループ予定を${plan.shiftMinutes}分ずらしました')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('グループ予定を変更できませんでした: $error')),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool _sameImpact(GroupScheduleImpact latest, GroupScheduleImpact shown) {
    return latest.affectedEntry.id == shown.affectedEntry.id &&
        latest.affectedEntry.plannedAt
            .isAtSameMomentAs(shown.affectedEntry.plannedAt) &&
        latest.arrival.legIndex == shown.arrival.legIndex &&
        latest.arrival.expectedArrivalAt
            .isAtSameMomentAs(shown.arrival.expectedArrivalAt) &&
        latest.overrun == shown.overrun;
  }

  static int _ceilMinutes(Duration duration) {
    final seconds = duration.inSeconds;
    if (seconds <= 0) {
      throw StateError('グループ予定調整量が正ではありません: $duration');
    }
    return (seconds + 59) ~/ 60;
  }

  static String _clock(DateTime value) {
    final local = value.toLocal();
    return '${local.hour.toString().padLeft(2, '0')}:'
        '${local.minute.toString().padLeft(2, '0')}';
  }
}
