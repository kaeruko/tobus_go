import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../l10n/navigation_localizations.dart';
import '../l10n/transit_name_localizations.dart';
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
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final mainText = localizedNavigationText(
      l10n,
      locale,
      navState.mainTextToken,
      fallback: navState.mainText,
    );
    final subText = localizedNavigationText(
      l10n,
      locale,
      navState.subTextToken,
      fallback: navState.subText,
    );
    final statusLabel = localizedNavigationText(
      l10n,
      locale,
      navState.statusLabelToken,
      fallback: navState.statusLabel,
    );
    final noticeText = navState.noticeText == null
        ? null
        : localizedNavigationText(
            l10n,
            locale,
            navState.noticeTextToken,
            fallback: navState.noticeText!,
          );
    final nextStopName = _localizedNextStopName(locale);
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
                  label: Text(statusLabel),
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
              mainText,
              style: const TextStyle(fontSize: 42, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            Text(
              subText,
              style: const TextStyle(fontSize: 21, fontWeight: FontWeight.bold),
            ),
            if (noticeText != null) ...[
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
                        noticeText,
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
                (nextStopName?.isNotEmpty ?? false)) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (navState.remainingStops != null)
                    ActionChip(
                      avatar: Icon(_remainingIcon(), size: 18),
                      label: Text(_remainingLabel(l10n)),
                      onPressed: onTapStops,
                    ),
                  if (nextStopName?.isNotEmpty ?? false)
                    Chip(
                      label: Text(l10n.nextStop(nextStopName!)),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  String? _localizedNextStopName(Locale locale) {
    final japanese = navState.nextStopName?.trim();
    if (japanese == null || japanese.isEmpty) return null;

    if (navState.step?.isRide == true) {
      return localizedOptionalTransitName(
        locale,
        japanese: japanese,
        english: navState.nextStopNameEn,
        field: 'nextStopNameEn',
        identity: 'stepId=${navState.step!.stepId}',
      );
    }

    if (isEnglishTransitLocale(locale)) {
      final english = navState.nextStopNameEn?.trim();
      if (english != null && english.isNotEmpty) return english;
    }
    return japanese;
  }

  String _remainingLabel(AppLocalizations l10n) {
    final remaining = navState.remainingStops;
    if (remaining == null) {
      throw StateError('remainingStops がない状態で残り表示を構築しました');
    }

    switch (navState.step?.kind) {
      case 'bus':
        return l10n.remainingBusStops(remaining);
      case 'rail':
        return l10n.remainingRailStops(remaining);
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
