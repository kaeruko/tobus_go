import 'package:flutter/material.dart';

import '../logic/trip_navigator.dart';

/// Shared navigation status card used by both solo and group navigation.
///
/// The changing route state (waiting, approaching, riding, arrival, etc.) is
/// represented entirely by [NavigationState]. Keeping the visual rendering in
/// one widget prevents solo/group screens from drifting when new navigation
/// states are added.
class TripNavigationStatusCard extends StatelessWidget {
  final NavigationState navState;
  final String tripTitle;
  final VoidCallback onTapStops;
  final Widget? headerTrailing;

  const TripNavigationStatusCard({
    super.key,
    required this.navState,
    required this.tripTitle,
    required this.onTapStops,
    this.headerTrailing,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      elevation: 4,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                Chip(
                  avatar: const Icon(Icons.location_on, size: 18),
                  label: Text(navState.statusLabel),
                ),
                Chip(
                  avatar: const Icon(Icons.route, size: 18),
                  label: Text(tripTitle),
                ),
              ],
            ),
            if (headerTrailing != null) ...[
              const SizedBox(height: 8),
              Align(alignment: Alignment.centerRight, child: headerTrailing!),
            ],
            const SizedBox(height: 18),
            Text(
              navState.mainText,
              style: const TextStyle(fontSize: 42, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            Text(
              navState.subText,
              style: const TextStyle(fontSize: 21, fontWeight: FontWeight.bold),
            ),
            if (navState.noticeText != null) ...[
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.amber.shade100,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.amber.shade700),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.sync, size: 22),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        navState.noticeText!,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (navState.remainingStops != null ||
                (navState.nextStopName?.isNotEmpty ?? false)) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (navState.remainingStops != null)
                    ActionChip(
                      avatar: Icon(_remainingIcon(), size: 18),
                      label: Text(_remainingLabel()),
                      onPressed: onTapStops,
                    ),
                  if (navState.nextStopName?.isNotEmpty ?? false)
                    Chip(label: Text('次: ${navState.nextStopName}')),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  String _remainingLabel() {
    final remaining = navState.remainingStops;
    if (remaining == null) {
      throw StateError('remainingStops がない状態で残り表示を構築しました');
    }

    switch (navState.step?.kind) {
      case 'bus':
        return 'のこり $remaining 回停車';
      case 'rail':
        return 'のこり $remaining 駅';
      default:
        throw StateError(
          '残り停車数表示の未対応step kindです: ${navState.step?.kind}',
        );
    }
  }

  IconData _remainingIcon() {
    switch (navState.step?.kind) {
      case 'bus':
        return Icons.directions_bus;
      case 'rail':
        return Icons.train;
      default:
        throw StateError(
          '残り停車数アイコンの未対応step kindです: ${navState.step?.kind}',
        );
    }
  }
}
