import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/route_replan_preview.dart';
import '../models/trip_models.dart';
import '../providers/route_replanner_provider.dart';
import 'route_replan_comparison_sheet.dart';

class RouteReplanPreviewButton extends ConsumerStatefulWidget {
  final Trip trip;

  const RouteReplanPreviewButton({
    super.key,
    required this.trip,
  });

  @override
  ConsumerState<RouteReplanPreviewButton> createState() =>
      _RouteReplanPreviewButtonState();
}

class _RouteReplanPreviewButtonState
    extends ConsumerState<RouteReplanPreviewButton> {
  bool _loading = false;

  @override
  Widget build(BuildContext context) {
    final request = ref.watch(currentRouteReplanRequestProvider);
    if (request == null) return const SizedBox.shrink();

    return OutlinedButton.icon(
      onPressed: _loading ? null : _openPreview,
      icon: _loading
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.alt_route),
      label: Text(_loading ? '新しい経路を検索中…' : '経路を見直す'),
    );
  }

  Future<void> _openPreview() async {
    final request = ref.read(currentRouteReplanRequestProvider);
    if (request == null || _loading) return;

    setState(() => _loading = true);
    try {
      final result = await ref.read(routeReplannerProvider).replan(request);
      final preview = RouteReplanPreview.build(
        trip: widget.trip,
        request: request,
        result: result,
      );
      if (!mounted) return;

      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Colors.transparent,
        builder: (_) => RouteReplanComparisonSheet(preview: preview),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('新しい経路を検索できませんでした: $error')),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }
}
