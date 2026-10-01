import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../constants.dart';
import '../l10n/app_localizations.dart';
import '../models/explore_models.dart';
import '../providers/explore_provider.dart';
import '../providers/location_provider.dart';
import 'experience_page.dart';

class ExplorePage extends ConsumerWidget {
  const ExplorePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final exploreState = ref.watch(exploreProvider);
    final editorialState = ref.watch(exploreEditorialContentProvider);
    final locationAsync = ref.watch(locationStreamProvider);
    final l10n = AppLocalizations.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.exploreTitle),
      ),
      body: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(16.0),
            color: Theme.of(context).canvasColor,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(l10n.exploreDescription),
                const SizedBox(height: 16),
                ElevatedButton.icon(
                  onPressed: locationAsync.valueOrNull == null
                      ? null
                      : () {
                          final override = ref.read(locationOverrideProvider);
                          final pos = override ??
                              LatLng(
                                locationAsync.value!.latitude,
                                locationAsync.value!.longitude,
                              );
                          ref.read(exploreProvider.notifier).search(pos);
                        },
                  icon: const Icon(Icons.explore),
                  label: Text(l10n.exploreNearbyButton),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: editorialState.when(
              data: (editorial) => exploreState.when(
                data: (data) {
                  if (data == null) {
                    return Center(
                      child: Text(l10n.exploreStartPrompt),
                    );
                  }
                  if (!data.found) {
                    return Center(
                      child: Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: Text(l10n.exploreNoNearbyStops),
                      ),
                    );
                  }
                  return _buildResultList(context, data, editorial);
                },
                error: (err, stack) => _errorView(
                  l10n.exploreSearchFailed('$err'),
                ),
                loading: () => Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const CircularProgressIndicator(),
                      const SizedBox(height: 16),
                      Text(l10n.exploreSearching),
                    ],
                  ),
                ),
              ),
              error: (err, stack) => _errorView(
                l10n.exploreContentLoadFailed('$err'),
              ),
              loading: () => Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const CircularProgressIndicator(),
                    const SizedBox(height: 16),
                    Text(l10n.exploreContentLoading),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _errorView(String message) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Text(
          message,
          style: const TextStyle(color: Colors.red),
        ),
      ),
    );
  }

  Uri _editorialImageUri(ExploreEditorialImage image) {
    return Uri.parse('$kApiBase/explore/content/image').replace(
      queryParameters: {'file': image.file},
    );
  }

  Widget _editorialThumb(ExploreEditorialImage image) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        width: 72,
        height: 72,
        child: Image.network(
          _editorialImageUri(image).toString(),
          fit: BoxFit.cover,
          errorBuilder: (context, error, stackTrace) {
            return Container(
              color: Colors.grey.shade200,
              child: const Icon(Icons.broken_image_outlined),
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

  Widget _streetViewThumb(ReachableStop stop) {
    final uri = Uri.parse('$kApiBase/streetview/thumb').replace(queryParameters: {
      'lat': stop.lat.toString(),
      'lon': stop.lon.toString(),
      'w': '120',
      'h': '120',
      'radius': '80',
      'fov': '90',
      'heading': '0',
      'pitch': '0',
    });

    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        width: 72,
        height: 72,
        child: Image.network(
          uri.toString(),
          fit: BoxFit.cover,
          errorBuilder: (context, error, stackTrace) {
            return Container(
              color: Colors.grey.shade200,
              child: const Icon(Icons.directions_bus_outlined),
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

  Widget _stopThumb(
    ReachableStop stop,
    ExploreEditorialSpot? editorial,
  ) {
    if (editorial != null && editorial.images.isNotEmpty) {
      return _editorialThumb(editorial.images.first);
    }
    return _streetViewThumb(stop);
  }

  Widget _buildResultList(
    BuildContext context,
    ReachableResponse data,
    ExploreEditorialContent editorial,
  ) {
    final l10n = AppLocalizations.of(context);
    final languageCode = Localizations.localeOf(context).languageCode;
    return ListView(
      children: [
        if (data.nearestStop != null)
          Container(
            color: Colors.grey.shade100,
            child: ListTile(
              leading: const Icon(Icons.my_location, color: Colors.blue),
              title: Text(
                l10n.exploreNearestStop(
                  data.nearestStop!.nameForLanguageCode(languageCode),
                ),
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              subtitle: Text(
                l10n.exploreDistanceFromCurrent(
                  data.nearestStop!.distM.round(),
                ),
              ),
            ),
          ),
        Padding(
          padding: const EdgeInsets.all(16.0),
          child: Text(
            l10n.exploreReachableCount(data.reachableStops.length),
            style: Theme.of(context).textTheme.titleSmall,
          ),
        ),
        ...data.reachableStops.map((stop) {
          final spot = editorial.byStopId[stop.id];
          final spotComment =
              spot?.commentForLanguageCode(languageCode) ?? '';
          final routeText = l10n.exploreRouteLabel(
            stop.viaRoute.replaceAll('odpt.Busroute:Toei.', ''),
          );

          return ListTile(
            leading: _stopThumb(stop, spot),
            title: Text(stop.nameForLanguageCode(languageCode)),
            subtitle: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  routeText,
                  style: const TextStyle(fontSize: 12),
                ),
                if (spotComment.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    spotComment,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => ExperiencePage(
                    stop: stop,
                    editorial: spot,
                  ),
                ),
              );
            },
          );
        }),
      ],
    );
  }
}
