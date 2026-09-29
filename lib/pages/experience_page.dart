import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../constants.dart';
import '../l10n/app_localizations.dart';
import '../models/explore_models.dart';
import '../providers/explore_provider.dart';
import '../providers/location_provider.dart';
import '../providers/navigation_provider.dart';
import '../providers/route_search_provider.dart';

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
      final res =
          await ref.read(exploreProvider.notifier).fetchExperiences(widget.stop);
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
    final l10n = AppLocalizations.of(context);
    final editorialState = ref.watch(exploreEditorialContentProvider);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.experienceAround(widget.stop.nameForLanguageCode(Localizations.localeOf(context).languageCode)))),
      body: _buildBody(editorialState),
    );
  }

  Widget _buildBody(AsyncValue<ExploreEditorialContent> editorialState) {
    final l10n = AppLocalizations.of(context);
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return _errorView(l10n.errorWithMessage(_error!));
    }
    if (_data == null) {
      return _errorView(l10n.experienceLoadFailed);
    }

    return editorialState.when(
      data: (editorial) => _buildLoadedBody(
        editorial.byStopId[widget.stop.id],
      ),
      error: (err, stack) => _errorView(
        l10n.exploreContentLoadFailed(err.toString()),
      ),
      loading: () => const Center(child: CircularProgressIndicator()),
    );
  }

  Widget _errorView(String message) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          message,
          style: const TextStyle(color: Colors.red),
        ),
      ),
    );
  }

  Widget _buildLoadedBody(ExploreEditorialSpot? editorial) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (editorial != null) ...[
          _editorialSection(editorial),
          const SizedBox(height: 20),
        ],
        _streetViewGallery(widget.stop),
        const SizedBox(height: 20),
        if (_data!.groups.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Text(AppLocalizations.of(context).experienceEmpty),
          )
        else
          ..._data!.groups.map(_experienceCard),
      ],
    );
  }

  Widget _experienceCard(ExperienceGroup group) {
    final l10n = AppLocalizations.of(context);
    final stop = group.representativeStop.id == widget.stop.id
        ? widget.stop : group.representativeStop;
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              children: group.tags
                  .map(
                    (t) => Chip(
                      label: Text(_experienceTag(t)),
                      backgroundColor: Colors.teal.shade50,
                      labelStyle: TextStyle(color: Colors.teal.shade900),
                    ),
                  )
                  .toList(),
            ),
            const SizedBox(height: 12),
            Text(
              _experienceDescription(group.description),
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              l10n.experienceCentralStop(stop.nameForLanguageCode(Localizations.localeOf(context).languageCode)),
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                const Icon(Icons.place, size: 16, color: Colors.grey),
                const SizedBox(width: 4),
                Text(
                  l10n.experienceSpotCount(group.stopCount),
                  style: const TextStyle(color: Colors.grey),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton.icon(
                  onPressed: () {
                    _goToRouteSearch(context, stop);
                  },
                  icon: const Icon(Icons.directions),
                  label: Text(l10n.experienceGoHere),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _experienceTag(String tag) {
    final l10n = AppLocalizations.of(context);
    return switch (tag) {
      '川沿い' => l10n.experienceTagWater,
      '公園' => l10n.experienceTagPark,
      '商店街' => l10n.experienceTagShopping,
      '歴史' => l10n.experienceTagHistory,
      _ => tag,
    };
  }

  String _experienceDescription(String description) {
    final l10n = AppLocalizations.of(context);
    return switch (description) {
      '川沿いをのんびり散歩できるエリア' => l10n.experienceWaterPark,
      '昔ながらの商店街をぶらぶら楽しめる' => l10n.experienceShopping,
      '寺社が点在する落ち着いた下町エリア' => l10n.experienceHistory,
      '近所で気軽にひと休みできるエリア' => l10n.experiencePark,
      '静かな住宅エリアを感じられる' => l10n.experienceResidential,
      _ => description,
    };
  }

  Uri _editorialImageUri(ExploreEditorialImage image) {
    return Uri.parse('$kApiBase/explore/content/image').replace(
      queryParameters: {'file': image.file},
    );
  }

  Widget _editorialSection(ExploreEditorialSpot editorial) {
    final languageCode = Localizations.localeOf(context).languageCode;
    final comment = editorial.commentForLanguageCode(languageCode);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          AppLocalizations.of(context).experienceMemo,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
        ),
        if (comment.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(comment),
        ],
        if (editorial.images.isNotEmpty) ...[
          const SizedBox(height: 12),
          SizedBox(
            height: 210,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: editorial.images.length,
              separatorBuilder: (context, index) => const SizedBox(width: 10),
              itemBuilder: (context, index) {
                final image = editorial.images[index];
                final caption = image.captionForLanguageCode(languageCode);
                return SizedBox(
                  width: 240,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      GestureDetector(
                        onTap: () => _openEditorialImage(image),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(12),
                          child: SizedBox(
                            width: 240,
                            height: 160,
                            child: Image.network(
                              _editorialImageUri(image).toString(),
                              fit: BoxFit.cover,
                              errorBuilder: (context, error, stackTrace) {
                                return Container(
                                  color: Colors.grey.shade200,
                                  child: const Center(
                                    child: Icon(
                                      Icons.broken_image_outlined,
                                      size: 40,
                                    ),
                                  ),
                                );
                              },
                              loadingBuilder:
                                  (context, child, loadingProgress) {
                                if (loadingProgress == null) return child;
                                return Container(
                                  color: Colors.grey.shade100,
                                  child: const Center(
                                    child: CircularProgressIndicator(),
                                  ),
                                );
                              },
                            ),
                          ),
                        ),
                      ),
                      if (caption.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          caption,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ],
    );
  }

  void _openEditorialImage(ExploreEditorialImage image) {
    showDialog(
      context: context,
      builder: (context) {
        return Dialog(
          insetPadding: const EdgeInsets.all(16),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Image.network(
              _editorialImageUri(image).toString(),
              fit: BoxFit.contain,
              errorBuilder: (context, error, stackTrace) {
                return Container(
                  constraints: const BoxConstraints(minHeight: 240),
                  color: Colors.grey.shade200,
                  child: const Center(
                    child: Icon(Icons.broken_image_outlined, size: 40),
                  ),
                );
              },
            ),
          ),
        );
      },
    );
  }

  Uri _svUri(
    ReachableStop stop, {
    required int w,
    required int h,
    required int heading,
  }) {
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
        Text(
          AppLocalizations.of(context).experienceSurroundings,
          style: Theme.of(context).textTheme.titleSmall,
        ),
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
                    child: const Center(
                      child: Icon(Icons.streetview, size: 40),
                    ),
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
    final override = ref.read(locationOverrideProvider);
    final currentAsync = ref.read(locationStreamProvider);

    String fromVal = '';
    const fromNameJa = '現在地';
    const fromNameEn = 'Current location';
    final fromName = AppLocalizations.of(context).currentLocationLabel;

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

    final notifier = ref.read(routeSearchProvider.notifier);

    if (fromVal.isNotEmpty) {
      notifier.setFrom(
        fromVal,
        name: fromName,
        nameJa: fromNameJa,
        nameEn: fromNameEn,
      );
    }

    notifier.setTo(
      '${stop.lat},${stop.lon}',
      name: stop.nameForLanguageCode(Localizations.localeOf(context).languageCode),
      nameJa: stop.name,
      nameEn: stop.nameEn,
    );
    print(
      '[ExperiencePage] RouteSearch params set. '
      'From=$fromVal, To=${stop.name}',
    );

    print('[ExperiencePage] Switching tab to 0');
    ref.read(tabIndexProvider.notifier).state = 0;

    if (fromVal.isNotEmpty) {
      print('[ExperiencePage] Triggering search');
      notifier.triggerSearch();
    }
  }
}
