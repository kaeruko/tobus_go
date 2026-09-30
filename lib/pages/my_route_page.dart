import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/saved_routes_provider.dart';
import '../widgets/route_card.dart';
import 'route_detail_page.dart';

class MyRoutePage extends ConsumerWidget {
  const MyRoutePage({super.key});

  Future<void> _editMemo(
    BuildContext context,
    WidgetRef ref, {
    required int index,
    required String? currentMemo,
  }) async {
    final l10n = AppLocalizations.of(context);
    final controller = TextEditingController(text: currentMemo ?? '');
    final result = await showCupertinoDialog<String>(
      context: context,
      builder: (dialogContext) => CupertinoAlertDialog(
        title: Text(l10n.savedRouteMemoTitle),
        content: Padding(
          padding: const EdgeInsets.only(top: 12),
          child: CupertinoTextField(
            controller: controller,
            autofocus: true,
            maxLines: 5,
            maxLength: SavedRoutesNotifier.maxMemoLength,
            placeholder: l10n.savedRouteMemoPlaceholder,
          ),
        ),
        actions: [
          CupertinoDialogAction(
            onPressed: () => Navigator.pop(dialogContext),
            child: Text(l10n.cancel),
          ),
          CupertinoDialogAction(
            isDefaultAction: true,
            onPressed: () => Navigator.pop(dialogContext, controller.text),
            child: Text(l10n.settingsSave),
          ),
        ],
      ),
    );
    controller.dispose();

    if (result == null || !context.mounted) return;
    await ref.read(savedRoutesProvider.notifier).updateMemo(index, result);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final savedRoutes = ref.watch(savedRoutesProvider);

    return CupertinoPageScaffold(
      backgroundColor: CupertinoColors.white,
      navigationBar: CupertinoNavigationBar(
        backgroundColor: CupertinoColors.white,
        middle: Text(l10n.myRouteTitle),
      ),
      child: ColoredBox(
        color: CupertinoColors.white,
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
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        GestureDetector(
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
                          child: RouteCard(
                            candidate: candidate,
                            rank: index + 1,
                            showRank: false,
                          ),
                        ),
                        const SizedBox(height: 6),
                        if (candidate.savedRouteMemo?.trim().isNotEmpty == true)
                          Container(
                            padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
                            decoration: BoxDecoration(
                              color: CupertinoColors.systemGrey6.resolveFrom(
                                context,
                              ),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Padding(
                                  padding: EdgeInsets.only(top: 2),
                                  child: Icon(
                                    CupertinoIcons.pencil,
                                    size: 17,
                                    color: CupertinoColors.systemGrey,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    candidate.savedRouteMemo!.trim(),
                                    maxLines: 3,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontSize: 14,
                                      height: 1.35,
                                    ),
                                  ),
                                ),
                                CupertinoButton(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 8,
                                    vertical: 2,
                                  ),
                                  onPressed: () => _editMemo(
                                    context,
                                    ref,
                                    index: index,
                                    currentMemo: candidate.savedRouteMemo,
                                  ),
                                  child: Text(l10n.savedRouteEditMemo),
                                ),
                              ],
                            ),
                          )
                        else
                          Align(
                            alignment: Alignment.centerLeft,
                            child: CupertinoButton(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 4,
                                vertical: 6,
                              ),
                              onPressed: () => _editMemo(
                                context,
                                ref,
                                index: index,
                                currentMemo: null,
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  const Icon(CupertinoIcons.pencil, size: 16),
                                  const SizedBox(width: 6),
                                  Text(l10n.savedRouteAddMemo),
                                ],
                              ),
                            ),
                          ),
                      ],
                    ),
                  );
                },
                ),
        ),
      ),
    );
  }
}
