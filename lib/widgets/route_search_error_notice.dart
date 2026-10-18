import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_client.dart';
import '../l10n/app_localizations.dart';
import '../providers/route_search_provider.dart';

/// Passenger-facing failure copy and explicit actions for a stopped search.
class RouteSearchErrorNotice extends ConsumerWidget {
  const RouteSearchErrorNotice({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(routeSearchProvider);
    if (state.errorMessage == null) return const SizedBox.shrink();

    final l10n = AppLocalizations.of(context);
    final notifier = ref.read(routeSearchProvider.notifier);
    final error = state.error;
    final isSearchLimit = error is ApiException &&
        error.code == 'route_search_limit';
    final canSearchByTime = isSearchLimit &&
        state.pref != 'shortTime' && state.pref != 'time';

    return Semantics(
      container: true,
      liveRegion: true,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(
                  CupertinoIcons.exclamationmark_circle,
                  size: 32,
                  color: CupertinoColors.systemOrange,
                ),
                const SizedBox(height: 16),
                Text(
                  l10n.routeSearchErrorTitle,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 12),
                Text(
                  isSearchLimit
                      ? l10n.routeSearchLimitMessage
                      : l10n.routeSearchErrorMessage,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 15,
                    height: 1.5,
                    color: CupertinoColors.secondaryLabel.resolveFrom(context),
                  ),
                ),
                const SizedBox(height: 24),
                if (canSearchByTime) ...[
                  CupertinoButton.filled(
                    key: const ValueKey('route-search-by-time'),
                    onPressed: () {
                      notifier.setPref('shortTime');
                      notifier.triggerSearch();
                    },
                    child: Text(l10n.routeSearchByTime),
                  ),
                  const SizedBox(height: 8),
                ],
                CupertinoButton(
                  key: const ValueKey('route-search-retry'),
                  onPressed: () => notifier.triggerSearch(),
                  child: Text(l10n.retry),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
