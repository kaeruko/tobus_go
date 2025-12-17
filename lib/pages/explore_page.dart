import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../providers/explore_provider.dart';
import '../providers/location_provider.dart';
import '../models/explore_models.dart';

class ExplorePage extends ConsumerWidget {
  const ExplorePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final exploreState = ref.watch(exploreProvider);
    // 現在地ストリームを監視
    final locationAsync = ref.watch(locationStreamProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('一本で行ける場所を探す'),
      ),
      body: Column(
        children: [
          // 検索アクションエリア
          Container(
            padding: const EdgeInsets.all(16.0),
            color: Theme.of(context).canvasColor,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('現在地から乗り換えなしで行ける\n都営交通の駅・バス停を探します。'),
                const SizedBox(height: 16),
                ElevatedButton.icon(
                  onPressed: locationAsync.valueOrNull == null
                      ? null // 位置情報が取れるまでボタン無効
                      : () {
                          final pos = locationAsync.value!;
                          ref.read(exploreProvider.notifier).search(
                                LatLng(pos.latitude, pos.longitude),
                              );
                        },
                  icon: const Icon(Icons.explore),
                  label: const Text('周辺を探索する'),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          
          // 結果表示エリア
          Expanded(
            child: exploreState.when(
              data: (data) {
                if (data == null) {
                  return const Center(child: Text('ボタンを押して検索を開始してください'));
                }
                if (!data.found) {
                  return Center(
                    child: Padding(
                      padding: const EdgeInsets.all(16.0),
                      child: Text(data.message ?? '近くにバス停が見つかりませんでした'),
                    ),
                  );
                }
                return _buildResultList(context, data);
              },
              error: (err, stack) => Center(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Text('エラーが発生しました: $err', style: const TextStyle(color: Colors.red)),
                ),
              ),
              loading: () => const Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(),
                    SizedBox(height: 16),
                    Text('検索中...'),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildResultList(BuildContext context, ReachableResponse data) {
    return ListView(
      children: [
        // 最寄りバス停情報
        if (data.nearestStop != null)
          Container(
            color: Colors.grey.shade100,
            child: ListTile(
              leading: const Icon(Icons.my_location, color: Colors.blue),
              title: Text(
                '最寄り: ${data.nearestStop!.name}',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              subtitle: Text(
                '現在地から約${data.nearestStop!.distM.toStringAsFixed(0)}m',
              ),
            ),
          ),
        
        Padding(
          padding: const EdgeInsets.all(16.0),
          child: Text(
            '${data.reachableStops.length}箇所の駅・バス停へ一本で行けます',
            style: Theme.of(context).textTheme.titleSmall,
          ),
        ),

        // 行ける場所リスト
        ...data.reachableStops.map((stop) {
          return ListTile(
            leading: const Icon(Icons.directions_bus_outlined),
            title: Text(stop.name),
            subtitle: Text(
              '系統: ${stop.viaRoute.replaceAll("odpt.Busroute:Toei.", "")}',
              style: const TextStyle(fontSize: 12),
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: () {
              // TODO: ここをタップしたら、その場所周辺のスポット紹介(Step2)へ遷移する
              // 例: Navigator.push(...)
            },
          );
        }),
      ],
    );
  }
}