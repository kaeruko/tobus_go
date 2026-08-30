import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../core/app_clock.dart';
import '../models/route_models.dart';
import '../widgets/bus_loading_indicator.dart';
import '../widgets/place_field.dart';
import '../widgets/route_card.dart';
import 'map_picker_page.dart';
import 'route_detail_page.dart';
import '../providers/effective_location_provider.dart';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/route_search_provider.dart';
import '../providers/active_trip_provider.dart';
import '../providers/city_profile_provider.dart';
import '../models/trip_models.dart';
import 'leader_mode_page.dart';
import 'trip_page.dart';

import 'package:flutter/material.dart' show Colors, Icons;

// UI enum values differ from backend search modes:
// - 'shortTime' is converted to 'time' on the API side
// - 'fewTransfers' is passed through as-is (comfort/乗換少ない優先)
enum Preference { fewTransfers, shortTime }

class RouteSearchPage extends ConsumerStatefulWidget {
  final String title;
  final ValueListenable<int>? tabIndexListenable;
  const RouteSearchPage({
    super.key,
    this.title = '都営でGO',
    this.tabIndexListenable,
  });

  @override
  ConsumerState<RouteSearchPage> createState() => RouteSearchPageState();
}

class RouteSearchPageState extends ConsumerState<RouteSearchPage> {
  // Controllers removed! State is now purely in providers.

  @override
  void initState() {
    super.initState();
    // Refresh active trip on init
    if (ref.read(cityProfileProvider).capabilities.features.groupTrips) {
      Future.microtask(() => ref.read(activeTripProvider.notifier).refresh());
    }
    widget.tabIndexListenable?.addListener(_handleTabChange);
  }

  @override
  void didUpdateWidget(covariant RouteSearchPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.tabIndexListenable != widget.tabIndexListenable) {
      oldWidget.tabIndexListenable?.removeListener(_handleTabChange);
      widget.tabIndexListenable?.addListener(_handleTabChange);
    }
  }

  void _handleTabChange() {
    if (widget.tabIndexListenable?.value == 0 &&
        ref.read(cityProfileProvider).capabilities.features.groupTrips) {
      ref.read(activeTripProvider.notifier).refresh();
    }
  }

  void _swapRouteEndpoints() {
    final rs = ref.read(routeSearchProvider);
    final notifier = ref.read(routeSearchProvider.notifier);

    notifier.setFrom(rs.to, name: rs.toName);
    notifier.setTo(rs.from, name: rs.fromName);

    final after = ref.read(routeSearchProvider);
    final ok =
        _isCoordinateOrEmpty(after.from) && _isCoordinateOrEmpty(after.to);
    if (ok) {
      notifier.triggerSearch();
    }
  }

  Future<void> _useEffectiveLocation() async {
    try {
      final effective = await ref.read(effectiveLocationProvider.future);
      final notifier = ref.read(routeSearchProvider.notifier);
      notifier.setFrom(effective.loc, name: effective.name);

      if (_canAutoSearchAfterEditingFrom()) {
        notifier.triggerSearch();
      }
    } catch (e, st) {
      debugPrint('[RouteSearchPage] 現在地取得エラー: $e');
      debugPrintStack(stackTrace: st);

      if (!mounted) return;

      await showCupertinoDialog<void>(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('現在地を取得できませんでした'),
          content: Text('$e'),
          actions: [
            CupertinoDialogAction(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('OK'),
            ),
          ],
        ),
      );
    }
  }

  Future<void> _openMap(bool forA) async {
    final res = await Navigator.of(context).push<LatLng>(
      CupertinoPageRoute(builder: (_) => const MapPickerPage(title: '地図から選ぶ')),
    );
    if (res == null) return;
    final s = "${res.latitude},${res.longitude}";

    final notifier = ref.read(routeSearchProvider.notifier);
    if (forA) {
      notifier.setFrom(s, name: '地図で選択した場所');
      if (_canAutoSearchAfterEditingFrom()) {
        notifier.triggerSearch();
      }
    } else {
      notifier.setTo(s, name: '地図で選択した場所');
      if (_canAutoSearchAfterEditingTo()) {
        notifier.triggerSearch();
      }
    }
  }

  void _showTimePicker(DateTime current) {
    showCupertinoModalPopup(
      context: context,
      builder: (ctx) => Container(
        height: 250,
        color: CupertinoColors.systemBackground,
        child: Column(
          children: [
            SizedBox(
              height: 180,
              child: CupertinoDatePicker(
                mode: CupertinoDatePickerMode.dateAndTime,
                initialDateTime: current,
                use24hFormat: true,
                onDateTimeChanged: (val) {
                  // If user picks a time that is already past for today, assume they mean tomorrow.
                  // Only apply if the date part is effectively "Today".
                  final now = DateTime.now();
                  var selected = val;
                  if (selected.year == now.year &&
                      selected.month == now.month &&
                      selected.day == now.day) {
                    if (selected.isBefore(now)) {
                      selected = selected.add(const Duration(days: 1));
                    }
                  }
                  ref.read(routeSearchProvider.notifier).setStartTime(selected);
                },
              ),
            ),
            CupertinoButton(
              onPressed: () {
                Navigator.pop(ctx);
                ref.read(routeSearchProvider.notifier).triggerSearch();
              },
              child: const Text('完了'),
            ),
          ],
        ),
      ),
    );
  }

  bool _isCoordinate(String s) {
    if (s.isEmpty) return false;
    final parts = s.split(',');
    if (parts.length != 2) return false;
    final lat = double.tryParse(parts[0].trim());
    final lon = double.tryParse(parts[1].trim());
    return lat != null && lon != null;
  }

  bool _isCoordinateOrEmpty(String s) {
    final t = s.trim();
    if (t.isEmpty) return true;

    final parts = t.split(',');
    if (parts.length != 2) return false;

    final lat = double.tryParse(parts[0].trim());
    final lon = double.tryParse(parts[1].trim());
    if (lat == null || lon == null) return false;

    if (lat < -90 || lat > 90) return false;
    if (lon < -180 || lon > 180) return false;

    return true;
  }

  bool _canAutoSearchAfterEditingFrom() {
    final rs = ref.read(routeSearchProvider);
    return _isCoordinateOrEmpty(rs.to);
  }

  bool _canAutoSearchAfterEditingTo() {
    final rs = ref.read(routeSearchProvider);
    return _isCoordinateOrEmpty(rs.from);
  }

  @override
  Widget build(BuildContext context) {
    final rs = ref.watch(routeSearchProvider);
    final features = ref.watch(
      cityProfileProvider.select((profile) => profile.capabilities.features),
    );
    final activeTripAsync = features.groupTrips
        ? ref.watch(activeTripProvider)
        : null;
    final notifier = ref.read(routeSearchProvider.notifier);
    final startTime = rs.startTime ?? appClock.now();

    return GestureDetector(
      behavior: HitTestBehavior.translucent,
      onTap: () {
        // 画面タップでフォーカス解除してキーボードを閉じる
        FocusManager.instance.primaryFocus?.unfocus();
      },
      child: CupertinoPageScaffold(
        navigationBar: CupertinoNavigationBar(middle: Text(widget.title)),
        child: SafeArea(
          child: CustomScrollView(
            slivers: [
              // Active Trip Card
              if (activeTripAsync?.value != null &&
                  activeTripAsync!.value!.status != TripStatus.completed &&
                  activeTripAsync.value!.status != TripStatus.cancelled)
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: _ActiveTripCard(
                      trip: activeTripAsync.value!,
                      onTap: () {
                        Navigator.push(
                          context,
                          CupertinoPageRoute(
                            builder: (_) => activeTripAsync.value!.isSolo
                                ? TripPage(tripId: activeTripAsync.value!.id)
                                : LeaderModePage(
                                    tripId: activeTripAsync.value!.id,
                                  ),
                          ),
                        ).then((_) {
                          ref.read(activeTripProvider.notifier).refresh();
                        });
                      },
                    ),
                  ),
                ),

              SliverToBoxAdapter(
                child: Column(
                  children: [
                    const SizedBox(height: 8),

                    // Date Time
                    Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16.0,
                        vertical: 8.0,
                      ),
                      child: GestureDetector(
                        onTap: () => _showTimePicker(startTime),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 12,
                          ),
                          decoration: BoxDecoration(
                            color: CupertinoColors.white,
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(
                              color: CupertinoColors.separator,
                            ),
                          ),
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              const Text(
                                '出発日時',
                                style: TextStyle(fontSize: 14),
                              ),
                              Text(
                                '${startTime.month}/${startTime.day} ${startTime.hour.toString().padLeft(2, '0')}:${startTime.minute.toString().padLeft(2, '0')}',
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.bold,
                                  color: CupertinoColors.activeBlue,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),

                    // From
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: PlaceField(
                        label: '出発(検索)',
                        value: rs.from,
                        displayValue: rs.fromName,
                        onChanged: (val, desc) {
                          notifier.setFrom(
                            val,
                            name: desc.isNotEmpty ? desc : val,
                          );
                          if (_isCoordinate(val) &&
                              _canAutoSearchAfterEditingFrom()) {
                            notifier.triggerSearch();
                          }
                        },
                        onCurrentLocationPressed: _useEffectiveLocation,
                      ),
                    ),
                    const SizedBox(height: 4),

                    // Swap & Map
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Row(
                            children: [
                              CupertinoButton(
                                padding: const EdgeInsets.all(8),
                                child: const Icon(
                                  CupertinoIcons.arrow_up_arrow_down,
                                ),
                                onPressed: _swapRouteEndpoints,
                              ),
                            ],
                          ),
                          CupertinoButton(
                            padding: const EdgeInsets.all(8),
                            child: const Icon(CupertinoIcons.map_pin),
                            onPressed: () => _openMap(true),
                          ),
                        ],
                      ),
                    ),

                    const SizedBox(height: 8),

                    // To
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: PlaceField(
                        label: '到着(検索)',
                        value: rs.to,
                        displayValue: rs.toName,
                        onChanged: (val, desc) {
                          notifier.setTo(
                            val,
                            name: desc.isNotEmpty ? desc : val,
                          );
                          if (_isCoordinate(val) &&
                              _canAutoSearchAfterEditingTo()) {
                            notifier.triggerSearch();
                          }
                        },
                      ),
                    ),
                    const SizedBox(height: 4),

                    // Map (To)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: Align(
                        alignment: Alignment.centerRight,
                        child: CupertinoButton(
                          padding: const EdgeInsets.all(8),
                          child: const Icon(CupertinoIcons.map_pin),
                          onPressed: () => _openMap(false),
                        ),
                      ),
                    ),

                    const SizedBox(height: 8),

                    // Preference
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: CupertinoSlidingSegmentedControl<String>(
                        groupValue: rs.pref ?? 'fewTransfers',
                        // NOTE: Backend expects 'time'/'fast' for fastest route; see RouteSearchNotifier._normalizePreferenceForApi
                        // for the mapping from this UI value to API param.
                        children: const {
                          'fewTransfers': Text('乗換少ない優先'),
                          'shortTime': Text('時間短い優先'),
                        },
                        onValueChanged: (v) {
                          if (v == null) return;
                          notifier.setPref(v);
                          notifier.triggerSearch();
                        },
                      ),
                    ),

                    // Search Button (Optional but useful if auto-search fails or purely manual)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: SizedBox(
                        width: double.infinity,
                        child: CupertinoButton.filled(
                          onPressed: () {
                            notifier.triggerSearch();
                          },
                          child: const Text("検索"),
                        ),
                      ),
                    ),

                    const SizedBox(height: 24),
                  ],
                ),
              ),

              if (rs.meta?.destinationReachable == false)
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16.0,
                      vertical: 8.0,
                    ),
                    child: _FallbackNotice(meta: rs.meta!),
                  ),
                ),

              // Loading / Results / Error
              if (rs.isLoading)
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: Center(
                    child: Container(
                      width: 160,
                      height: 160,
                      decoration: BoxDecoration(
                        color: CupertinoColors.systemBackground,
                        borderRadius: BorderRadius.circular(16),
                        boxShadow: [
                          BoxShadow(
                            color: CupertinoColors.systemGrey.withOpacity(0.2),
                            blurRadius: 10,
                            offset: const Offset(0, 4),
                          ),
                        ],
                      ),
                      child: const FittedBox(
                        fit: BoxFit.scaleDown,
                        child: BusLoadingIndicator(),
                      ),
                    ),
                  ),
                )
              else if (rs.errorMessage != null)
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: Center(
                    child: Text(
                      'エラー: ${rs.errorMessage}',
                      style: const TextStyle(
                        color: CupertinoColors.destructiveRed,
                      ),
                    ),
                  ),
                )
              else if (rs.candidates.isEmpty)
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: Center(
                    child: Text(
                      rs.hasSearched ? '経路が見つかりませんでした' : '出発と到着を選択',
                      style: TextStyle(
                        color: rs.hasSearched
                            ? CupertinoColors.systemRed
                            : CupertinoColors.systemGrey,
                      ),
                    ),
                  ),
                )
              else
                SliverList(
                  delegate: SliverChildBuilderDelegate((context, i) {
                    final c = rs.candidates[i];
                    return Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16.0,
                        vertical: 6.0,
                      ),
                      child: GestureDetector(
                        onTap: () {
                          Navigator.of(context).push(
                            CupertinoPageRoute(
                              builder: (_) => RouteDetailPage(
                                candidate: c,
                                meta: rs.meta,
                                fare: rs.fareByCandidateId[c.id],
                              ),
                            ),
                          );
                        },
                        child: RouteCard(
                          candidate: c,
                          rank: i + 1,
                          meta: rs.meta,
                        ),
                      ),
                    );
                  }, childCount: rs.candidates.length),
                ),

              const SliverPadding(padding: EdgeInsets.only(bottom: 24)),
            ],
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    widget.tabIndexListenable?.removeListener(_handleTabChange);
    super.dispose();
  }
}

class _FallbackNotice extends StatelessWidget {
  final RouteMeta meta;
  const _FallbackNotice({required this.meta});

  @override
  Widget build(BuildContext context) {
    final stopName = meta.fallbackNodeName ?? '最寄り停留所';
    final walkMinutes = meta.fallbackWalkMinutes;
    final distance = meta.fallbackDistanceM;
    String walkText;
    if (walkMinutes != null) {
      walkText = '徒歩約${walkMinutes}分';
    } else if (distance != null) {
      final formatted = distance >= 1000
          ? '${(distance / 1000).toStringAsFixed(1)}km'
          : '${distance.toStringAsFixed(0)}m';
      walkText = '徒歩${formatted}程度';
    } else {
      walkText = '徒歩圏内';
    }

    final limitText = meta.walkLimitM != null
        ? '（徒歩上限${meta.walkLimitM}m内で探索）'
        : '';

    return Container(
      decoration: BoxDecoration(
        color: CupertinoColors.systemYellow.withOpacity(0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: CupertinoColors.systemYellow),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(
                CupertinoIcons.exclamationmark_triangle_fill,
                color: CupertinoColors.systemOrange,
              ),
              SizedBox(width: 8),
              Text(
                '目的地までの都営経路が見つかりません',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  color: CupertinoColors.activeOrange,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '都営だけでは${meta.destinationLabel}の近くまで行けません。最寄りは「$stopName」で、ここから$walkText。',
            style: const TextStyle(fontSize: 14),
          ),
          const SizedBox(height: 4),
          Text(
            'それでもこの経路を使いますか？$limitText',
            style: const TextStyle(
              color: CupertinoColors.inactiveGray,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}

// ★ 追加: ホーム画面に表示する「進行中の旅」カード
class _ActiveTripCard extends StatelessWidget {
  final Trip trip;
  final VoidCallback onTap;

  const _ActiveTripCard({required this.trip, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final displayTitle = trip.displayTitle;

    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          // 目立つようにグラデーションや色をつける
          gradient: LinearGradient(
            colors: [Colors.orange.shade400, Colors.deepOrange.shade400],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(16),
          boxShadow: [
            BoxShadow(
              color: Colors.orange.withOpacity(0.3),
              blurRadius: 8,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          children: [
            const Icon(
              Icons.directions_bus_filled,
              color: Colors.white,
              size: 32,
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    trip.isSolo ? "現在進行中の移動" : "現在進行中のグループ",
                    style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    displayTitle,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: Colors.white.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          trip.status == TripStatus.planning ? "計画中" : "移動中",
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                          ),
                        ),
                      ),
                      if (!trip.isSolo) ...[
                        const SizedBox(width: 8),
                        Text(
                          "${trip.participants.length}人が参加中",
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
            const Icon(
              Icons.arrow_forward_ios,
              color: Colors.white54,
              size: 16,
            ),
          ],
        ),
      ),
    );
  }
}
