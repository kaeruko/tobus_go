import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../providers/effective_location_provider.dart';
import '../providers/route_search_provider.dart';
import '../widgets/bus_loading_indicator.dart';
import '../widgets/place_field.dart';
import '../widgets/route_card.dart';
import 'route_detail_page.dart';

/// Route-search-only home screen for the Nagoya edition.
///
/// This page deliberately has no outing discovery, favorites, history,
/// group/member mode, or active-trip UI.
class NagoyaHomePage extends ConsumerWidget {
  const NagoyaHomePage({super.key});

  bool _isCoordinate(String value) {
    final parts = value.split(',');
    if (parts.length != 2) return false;
    final lat = double.tryParse(parts[0].trim());
    final lon = double.tryParse(parts[1].trim());
    if (lat == null || lon == null) return false;
    return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
  }

  Future<void> _useCurrentLocation(WidgetRef ref) async {
    final effective = await ref.read(effectiveLocationProvider.future);
    ref
        .read(routeSearchProvider.notifier)
        .setFrom(effective.loc, name: effective.name);
  }

  void _swap(WidgetRef ref) {
    final state = ref.read(routeSearchProvider);
    final notifier = ref.read(routeSearchProvider.notifier);
    notifier.setFrom(state.to, name: state.toName);
    notifier.setTo(state.from, name: state.fromName);
  }

  void _showTimePicker(BuildContext context, WidgetRef ref, DateTime current) {
    showCupertinoModalPopup<void>(
      context: context,
      builder: (ctx) => Container(
        height: 250,
        color: CupertinoColors.systemBackground.resolveFrom(ctx),
        child: Column(
          children: [
            SizedBox(
              height: 180,
              child: CupertinoDatePicker(
                mode: CupertinoDatePickerMode.dateAndTime,
                initialDateTime: current,
                use24hFormat: true,
                onDateTimeChanged: (value) {
                  ref.read(routeSearchProvider.notifier).setStartTime(value);
                },
              ),
            ),
            CupertinoButton(
              onPressed: () {
                Navigator.of(ctx).pop();
                ref.read(routeSearchProvider.notifier).triggerSearch();
              },
              child: const Text('完了'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(routeSearchProvider);
    final notifier = ref.read(routeSearchProvider.notifier);
    final startTime = state.startTime ?? appClock.now();

    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(
        middle: Text('名古屋でGO'),
      ),
      child: SafeArea(
        child: CustomScrollView(
          slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Column(
                  children: [
                    GestureDetector(
                      onTap: () => _showTimePicker(context, ref, startTime),
                      child: Container(
                        width: double.infinity,
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 12,
                        ),
                        decoration: BoxDecoration(
                          border: Border.all(
                            color: CupertinoColors.separator.resolveFrom(context),
                          ),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text('出発日時'),
                            Text(
                              '${startTime.month}/${startTime.day} '
                              '${startTime.hour.toString().padLeft(2, '0')}:'
                              '${startTime.minute.toString().padLeft(2, '0')}',
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                color: CupertinoColors.activeBlue,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    PlaceField(
                      label: '出発',
                      value: state.from,
                      displayValue: state.fromName,
                      onChanged: (value, description) {
                        notifier.setFrom(
                          value,
                          name: description.isEmpty ? value : description,
                        );
                      },
                      onCurrentLocationPressed: () async {
                        try {
                          await _useCurrentLocation(ref);
                        } catch (error) {
                          if (!context.mounted) return;
                          await showCupertinoDialog<void>(
                            context: context,
                            builder: (ctx) => CupertinoAlertDialog(
                              title: const Text('現在地を取得できませんでした'),
                              content: Text('$error'),
                              actions: [
                                CupertinoDialogAction(
                                  onPressed: () => Navigator.of(ctx).pop(),
                                  child: const Text('OK'),
                                ),
                              ],
                            ),
                          );
                        }
                      },
                    ),
                    CupertinoButton(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      onPressed: () => _swap(ref),
                      child: const Icon(CupertinoIcons.arrow_up_arrow_down),
                    ),
                    PlaceField(
                      label: '到着',
                      value: state.to,
                      displayValue: state.toName,
                      onChanged: (value, description) {
                        notifier.setTo(
                          value,
                          name: description.isEmpty ? value : description,
                        );
                      },
                    ),
                    const SizedBox(height: 16),
                    CupertinoSlidingSegmentedControl<String>(
                      groupValue: state.pref ?? 'fewTransfers',
                      children: const {
                        'fewTransfers': Text('乗換少ない'),
                        'shortTime': Text('時間短い'),
                      },
                      onValueChanged: (value) {
                        if (value == null) return;
                        notifier.setPref(value);
                      },
                    ),
                    const SizedBox(height: 16),
                    SizedBox(
                      width: double.infinity,
                      child: CupertinoButton.filled(
                        onPressed: () {
                          final from = ref.read(routeSearchProvider).from.trim();
                          final to = ref.read(routeSearchProvider).to.trim();
                          if (from.isEmpty || to.isEmpty) {
                            throw StateError(
                              'Both origin and destination are required',
                            );
                          }
                          if (!_isCoordinate(from) || !_isCoordinate(to)) {
                            throw StateError(
                              'Origin and destination must resolve to coordinates before search',
                            );
                          }
                          notifier.triggerSearch();
                        },
                        child: const Text('経路を検索'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            if (state.isLoading)
              const SliverFillRemaining(
                hasScrollBody: false,
                child: Center(child: BusLoadingIndicator()),
              )
            else if (state.errorMessage != null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: Center(
                  child: Text(
                    'エラー: ${state.errorMessage}',
                    style: const TextStyle(
                      color: CupertinoColors.destructiveRed,
                    ),
                  ),
                ),
              )
            else if (state.candidates.isEmpty)
              SliverFillRemaining(
                hasScrollBody: false,
                child: Center(
                  child: Text(
                    state.hasSearched ? '経路が見つかりませんでした' : '出発と到着を選択',
                    style: const TextStyle(
                      color: CupertinoColors.systemGrey,
                    ),
                  ),
                ),
              )
            else
              SliverList(
                delegate: SliverChildBuilderDelegate(
                  (context, index) {
                    final candidate = state.candidates[index];
                    return Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 6,
                      ),
                      child: GestureDetector(
                        onTap: () {
                          Navigator.of(context).push(
                            CupertinoPageRoute(
                              builder: (_) => RouteDetailPage(
                                candidate: candidate,
                                meta: state.meta,
                              ),
                            ),
                          );
                        },
                        child: RouteCard(
                          candidate: candidate,
                          rank: index + 1,
                          meta: state.meta,
                        ),
                      ),
                    );
                  },
                  childCount: state.candidates.length,
                ),
              ),
            const SliverPadding(padding: EdgeInsets.only(bottom: 24)),
          ],
        ),
      ),
    );
  }
}
