class ReachableStop {
  final String id;
  final String name;
  final double lat;
  final double lon;
  final String viaRoute; // 系統ID (例: odpt.Busroute:Toei.Higashi22)

  ReachableStop({
    required this.id,
    required this.name,
    required this.lat,
    required this.lon,
    required this.viaRoute,
  });

  factory ReachableStop.fromJson(Map<String, dynamic> json) {
    return ReachableStop(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      lat: (json['lat'] as num?)?.toDouble() ?? 0.0,
      lon: (json['lon'] as num?)?.toDouble() ?? 0.0,
      viaRoute: json['via_route'] as String? ?? '',
    );
  }
}

class NearestStop {
  final String id;
  final String name;
  final double lat;
  final double lon;
  final double distM;

  NearestStop({
    required this.id,
    required this.name,
    required this.lat,
    required this.lon,
    required this.distM,
  });

  factory NearestStop.fromJson(Map<String, dynamic> json) {
    return NearestStop(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      lat: (json['lat'] as num?)?.toDouble() ?? 0.0,
      lon: (json['lon'] as num?)?.toDouble() ?? 0.0,
      distM: (json['dist_m'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class ReachableResponse {
  final bool found;
  final String? message;
  final NearestStop? nearestStop;
  final List<ReachableStop> reachableStops;

  ReachableResponse({
    required this.found,
    this.message,
    this.nearestStop,
    required this.reachableStops,
  });

  factory ReachableResponse.fromJson(Map<String, dynamic> json) {
    return ReachableResponse(
      found: json['found'] as bool? ?? false,
      message: json['message'] as String?,
      nearestStop: json['nearest_stop'] != null
          ? NearestStop.fromJson(json['nearest_stop'] as Map<String, dynamic>)
          : null,
      reachableStops: (json['reachable_stops'] as List<dynamic>?)
              ?.map((e) => ReachableStop.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
    );
  }
}

class ExperienceGroup {
  final List<String> tags;
  final String description;
  final ReachableStop representativeStop;
  final int stopCount;
  final List<ReachableStop> stops;

  ExperienceGroup({
    required this.tags,
    required this.description,
    required this.representativeStop,
    required this.stopCount,
    required this.stops,
  });

  factory ExperienceGroup.fromJson(Map<String, dynamic> json) {
    final repData = json['representative_stop'] as Map<String, dynamic>;

    final representativeStop = ReachableStop(
      id: repData['stop_id'] as String? ?? '',
      name: repData['stop_name'] as String? ?? '',
      lat: (repData['lat'] as num?)?.toDouble() ?? 0.0,
      lon: (repData['lon'] as num?)?.toDouble() ?? 0.0,
      viaRoute: '',
    );

    final stopsList = (json['stops'] as List<dynamic>?)?.map((s) {
          final m = s as Map<String, dynamic>;
          return ReachableStop(
            id: m['stop_id'] ?? '',
            name: m['stop_name'] ?? '',
            lat: 0,
            lon: 0,
            viaRoute: '',
          );
        }).toList() ??
        [];

    return ExperienceGroup(
      tags: (json['tags'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          [],
      description: json['description'] as String? ?? '',
      representativeStop: representativeStop,
      stopCount: json['stop_count'] as int? ?? 0,
      stops: stopsList,
    );
  }
}

class ExperienceResponse {
  final List<ExperienceGroup> groups;

  ExperienceResponse({required this.groups});

  factory ExperienceResponse.fromJson(Map<String, dynamic> json) {
    return ExperienceResponse(
      groups: (json['groups'] as List<dynamic>?)
              ?.map(
                (e) => ExperienceGroup.fromJson(e as Map<String, dynamic>),
              )
              .toList() ??
          [],
    );
  }
}

void _expectExactKeys(
  Map<String, dynamic> json,
  Set<String> expected,
  String where,
) {
  final actual = json.keys.toSet();
  if (actual.length != expected.length ||
      !actual.containsAll(expected) ||
      !expected.containsAll(actual)) {
    throw FormatException(
      '$where keys mismatch: expected=$expected actual=$actual',
    );
  }
}

class ExploreEditorialImage {
  final String file;
  final String caption;

  const ExploreEditorialImage({
    required this.file,
    required this.caption,
  });

  factory ExploreEditorialImage.fromJson(
    Map<String, dynamic> json, {
    required String where,
  }) {
    _expectExactKeys(json, {'file', 'caption'}, where);

    final file = json['file'];
    final caption = json['caption'];
    if (file is! String || file.isEmpty) {
      throw FormatException('$where.file must be a non-empty string');
    }
    if (caption is! String) {
      throw FormatException('$where.caption must be a string');
    }

    return ExploreEditorialImage(file: file, caption: caption);
  }
}

class ExploreEditorialSpot {
  final String stopId;
  final String comment;
  final List<ExploreEditorialImage> images;

  const ExploreEditorialSpot({
    required this.stopId,
    required this.comment,
    required this.images,
  });

  factory ExploreEditorialSpot.fromJson(
    Map<String, dynamic> json, {
    required String where,
  }) {
    _expectExactKeys(json, {'stop_id', 'comment', 'images'}, where);

    final stopId = json['stop_id'];
    final comment = json['comment'];
    final rawImages = json['images'];

    if (stopId is! String || stopId.isEmpty || stopId.trim() != stopId) {
      throw FormatException(
        '$where.stop_id must be a non-empty string without surrounding whitespace',
      );
    }
    if (comment is! String) {
      throw FormatException('$where.comment must be a string');
    }
    if (rawImages is! List<dynamic>) {
      throw FormatException('$where.images must be a list');
    }

    final images = <ExploreEditorialImage>[];
    final seenFiles = <String>{};
    for (var i = 0; i < rawImages.length; i++) {
      final rawImage = rawImages[i];
      if (rawImage is! Map<String, dynamic>) {
        throw FormatException('$where.images[$i] must be an object');
      }
      final image = ExploreEditorialImage.fromJson(
        rawImage,
        where: '$where.images[$i]',
      );
      if (!seenFiles.add(image.file)) {
        throw FormatException(
          '$where contains duplicate image file ${image.file}',
        );
      }
      images.add(image);
    }

    if (comment.isEmpty && images.isEmpty) {
      throw FormatException('$where must contain a comment or image');
    }

    return ExploreEditorialSpot(
      stopId: stopId,
      comment: comment,
      images: images,
    );
  }
}

class ExploreEditorialContent {
  final Map<String, ExploreEditorialSpot> byStopId;

  ExploreEditorialContent({required Map<String, ExploreEditorialSpot> byStopId})
      : byStopId = Map.unmodifiable(byStopId);

  factory ExploreEditorialContent.fromJson(Map<String, dynamic> json) {
    _expectExactKeys(json, {'spots'}, 'root');

    final rawSpots = json['spots'];
    if (rawSpots is! List<dynamic>) {
      throw const FormatException('root.spots must be a list');
    }

    final byStopId = <String, ExploreEditorialSpot>{};
    for (var i = 0; i < rawSpots.length; i++) {
      final rawSpot = rawSpots[i];
      if (rawSpot is! Map<String, dynamic>) {
        throw FormatException('spots[$i] must be an object');
      }
      final spot = ExploreEditorialSpot.fromJson(
        rawSpot,
        where: 'spots[$i]',
      );
      if (byStopId.containsKey(spot.stopId)) {
        throw FormatException('duplicate stop_id: ${spot.stopId}');
      }
      byStopId[spot.stopId] = spot;
    }

    return ExploreEditorialContent(byStopId: byStopId);
  }
}
