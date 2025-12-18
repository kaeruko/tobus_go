
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/explore_models.dart';
import '../providers/explore_provider.dart';
import '../providers/route_search_provider.dart';
import '../providers/location_provider.dart';
import '../providers/navigation_provider.dart';

class ExperiencePage extends ConsumerStatefulWidget {
  final ReachableStop stop;

  const ExperiencePage({super.key, required this.stop});

  @override
  ConsumerState<ExperiencePage> createState() => _ExperiencePageState();
}

class _ExperiencePageState extends ConsumerState<ExperiencePage> {
  ExperienceResponse? _data;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await ref.read(exploreProvider.notifier).fetchExperiences(widget.stop);
      if (mounted) {
        setState(() {
          _data = res;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('${widget.stop.name}周辺')),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(child: Text('エラー: $_error', style: const TextStyle(color: Colors.red)));
    }
    if (_data == null || _data!.groups.isEmpty) {
      return const Center(child: Text('おすすめのスポットが見つかりませんでした'));
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _data!.groups.length,
      itemBuilder: (context, index) {
        final group = _data!.groups[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 16),
          elevation: 2,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Tags
                Wrap(
                  spacing: 8,
                  children: group.tags.map((t) => Chip(
                    label: Text(t),
                    backgroundColor: Colors.teal.shade50,
                    labelStyle: TextStyle(color: Colors.teal.shade900),
                  )).toList(),
                ),
                const SizedBox(height: 12),
                
                // Description
                Text(
                  group.description,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                
                // Representative Stop Info
                Text(
                  '中心となるバス停: ${group.representativeStop.name}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                
                // Stop Count
                Row(
                  children: [
                    const Icon(Icons.place, size: 16, color: Colors.grey),
                    const SizedBox(width: 4),
                    Text('${group.stopCount}箇所のスポットが含まれます', style: const TextStyle(color: Colors.grey)),
                  ],
                ),
                
                const SizedBox(height: 16),
                
                // Actions (Here is the Go Button)
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton.icon(
                      onPressed: () {
                        _goToRouteSearch(context, group.representativeStop);
                      },
                      icon: const Icon(Icons.directions),
                      label: const Text('ここに行く'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _goToRouteSearch(BuildContext context, ReachableStop stop) {
    print('[ExperiencePage] Go Here tapped for ${stop.name}');
    // 1. Get current location
    final override = ref.read(locationOverrideProvider);
    final currentAsync = ref.read(locationStreamProvider);
    
    // Default to override, then GPS, then empty
    String fromVal = '';
    String fromName = '現在地';
    
    if (override != null) {
      print('[ExperiencePage] Using override location');
      fromVal = '${override.latitude},${override.longitude}';
    } else if (currentAsync.valueOrNull != null) {
      print('[ExperiencePage] Using GPS location');
      final p = currentAsync.value!;
      fromVal = '${p.latitude},${p.longitude}';
    } else {
      print('[ExperiencePage] No location found');
    }
    
    // 2. Set Route Search State
    final notifier = ref.read(routeSearchProvider.notifier);
    
    // Set FROM only if we found a location, otherwise user can input
    if (fromVal.isNotEmpty) {
      notifier.setFrom(fromVal, name: fromName);
    }
    
    // Set TO
    notifier.setTo(
      '${stop.lat},${stop.lon}',
      name: stop.name,
    );
    print('[ExperiencePage] RouteSearch params set. From=$fromVal, To=${stop.name}');
    
    // 3. Switch to Home Tab (index 0)
    print('[ExperiencePage] Switching tab to 0');
    ref.read(tabIndexProvider.notifier).state = 0;
    
    // 4. Trigger Search immediately if we have both coordinates
    if (fromVal.isNotEmpty) {
        print('[ExperiencePage] Triggering search');
        notifier.triggerSearch();
    }
  }
}
