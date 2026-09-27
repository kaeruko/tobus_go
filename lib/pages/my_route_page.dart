import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/saved_routes_provider.dart';
import '../widgets/route_card.dart';
import 'route_detail_page.dart';

class MyRoutePage extends ConsumerWidget {
  const MyRoutePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final savedRoutes = ref.watch(savedRoutesProvider);

    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(l10n.myRouteTitle),
      ),
      child: SafeArea(
        child: savedRoutes.isEmpty
            ? Center(child: Text(l10n.savedRoutesEmpty))
            : ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
                itemCount: savedRoutes.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (context, index) {
                  final candidate = savedRoutes[index];
                  return Dismissible(
                    key: ValueKey('saved-route:${candidate.id}:$index'),
                    direction: DismissDirection.endToStart,
                    confirmDismiss: (_) => showCupertinoDialog<bool>(
                      context: context,
                      builder: (dialogContext) => CupertinoAlertDialog(
                        title: Text(l10n.deleteBookmarkTitle),
                        content: Text(l10n.deleteBookmarkMessage),
                        actions: [
                          CupertinoDialogAction(
                            onPressed: () =>
                                Navigator.pop(dialogContext, false),
                            child: Text(l10n.cancel),
                          ),
                          CupertinoDialogAction(
                            isDestructiveAction: true,
                            onPressed: () =>
                                Navigator.pop(dialogContext, true),
                            child: Text(l10n.delete),
                          ),
                        ],
                      ),
                    ),
                    onDismissed: (_) {
                      ref.read(savedRoutesProvider.notifier).removeAt(index);
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
                      onTap: () {
                        Navigator.of(context).push(
                          CupertinoPageRoute(
                            builder: (_) => RouteDetailPage(
                              candidate: candidate,
                              fromSavedRoute: true,
                            ),
                          ),
                        );
                      },
                      child: RouteCard(candidate: candidate, rank: index + 1),
                    ),
                  );
                },
              ),
      ),
    );
  }
}
