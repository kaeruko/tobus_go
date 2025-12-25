
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/explore_models.dart';
import '../providers/explore_provider.dart';
import '../providers/route_search_provider.dart';
import '../providers/location_provider.dart';
import '../providers/navigation_provider.dart';
import '../constants.dart';

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

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _streetViewGallery(widget.stop),
        const SizedBox(height: 16),
        ..._data!.groups.map((group) {
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
      }),
      ],
    );
  }

  Uri _svUri(ReachableStop stop, {required int w, required int h, required int heading}) {
    return Uri.parse('$kApiBase/streetview/thumb').replace(queryParameters: {
      'lat': stop.lat.toString(),
      'lon': stop.lon.toString(),
      'w': w.toString(),
      'h': h.toString(),
      'radius': '150',
      'fov': '90',
      'heading': heading.toString(),
      'pitch': '0',
    });
  }

  Widget _svThumb(ReachableStop stop, {required int heading}) {
    final uri = _svUri(stop, w: 240, h: 160, heading: heading);

    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: AspectRatio(
        aspectRatio: 3 / 2,
        child: Image.network(
          uri.toString(),
          fit: BoxFit.cover,
          errorBuilder: (context, error, stackTrace) {
            return Container(
              color: Colors.grey.shade200,
              child: const Icon(Icons.streetview),
            );
          },
          loadingBuilder: (context, child, loadingProgress) {
            if (loadingProgress == null) return child;
            return Container(
              color: Colors.grey.shade100,
              child: const Center(
                child: SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _streetViewGallery(ReachableStop stop) {
    final headings = <int>[0, 90, 180, 270];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('周辺のようす', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        SizedBox(
          height: 160,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: headings.length,
            separatorBuilder: (context, index) => const SizedBox(width: 10),
            itemBuilder: (context, index) {
              final heading = headings[index];
              return GestureDetector(
                onTap: () {
                  _openStreetViewFull(stop, heading: heading);
                },
                child: _svThumb(stop, heading: heading),
              );
            },
          ),
        ),
      ],
    );
  }

  void _openStreetViewFull(ReachableStop stop, {required int heading}) {
    final uri = _svUri(stop, w: 640, h: 360, heading: heading);

    showDialog(
      context: context,
      builder: (context) {
        return Dialog(
          insetPadding: const EdgeInsets.all(16),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: Image.network(
                uri.toString(),
                fit: BoxFit.cover,
                errorBuilder: (context, error, stackTrace) {
                  return Container(
                    color: Colors.grey.shade200,
                    child: const Center(child: Icon(Icons.streetview, size: 40)),
                  );
                },
              ),
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
