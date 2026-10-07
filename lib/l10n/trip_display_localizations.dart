import 'package:flutter/widgets.dart';

import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import 'app_localizations.dart';
import 'transit_name_localizations.dart';

String localizedSoloTripTitle(Locale locale, Trip trip) {
  if (!trip.isSolo || !isEnglishTransitLocale(locale)) {
    return trip.displayTitle;
  }
  if (trip.legs.isEmpty) {
    throw StateError('English solo trip title requires at least one leg');
  }

  final candidate = trip.legs.first.candidate;
  if (candidate.steps.isEmpty) {
    throw StateError(
      'English solo trip title requires route steps: tripId=${trip.id}',
    );
  }

  final first = candidate.steps.first;
  final last = candidate.steps.last;
  final origin = _localizedEndpoint(
    locale,
    japanese: candidate.originName ?? first.fromName,
    english: candidate.originNameEn ?? first.fromNameEn,
    field: 'origin_name_en',
    identity: 'candidateId=${candidate.id}',
  );
  final destination = _localizedEndpoint(
    locale,
    japanese: candidate.destinationName ?? last.toName,
    english: candidate.destinationNameEn ?? last.toNameEn,
    field: 'destination_name_en',
    identity: 'candidateId=${candidate.id}',
  );
  return '$origin → $destination';
}

String localizedGroupTripTitle(Locale locale, Trip trip) {
  if (trip.isSolo) {
    throw StateError(
      'localizedGroupTripTitle requires a group trip: tripId=${trip.id}',
    );
  }
  if (trip.legs.isEmpty) return trip.displayTitle;

  final leg = trip.legs.firstWhere(
    (leg) => leg.direction == LegDirection.outbound,
    orElse: () => trip.legs.first,
  );
  final candidate = leg.candidate;
  if (candidate.steps.isEmpty) return trip.displayTitle;

  final last = candidate.steps.last;
  final japanese = (candidate.destinationName ?? last.toName)?.trim();
  if (japanese == null || japanese.isEmpty || japanese == '目的地') {
    return trip.displayTitle;
  }
  final destination = _localizedEndpoint(
    locale,
    japanese: japanese,
    english: candidate.destinationNameEn ?? last.toNameEn,
    field: 'destination_name_en',
    identity: 'candidateId=${candidate.id}',
  );
  return lookupAppLocalizations(locale).groupTripTo(destination);
}

String localizedSoloScheduleEntryLabel(
  Locale locale, {
  required Trip trip,
  required ScheduleEntry entry,
}) {
  if (!trip.isSolo) {
    throw StateError(
      'localizedSoloScheduleEntryLabel requires a solo trip: tripId=${trip.id}',
    );
  }
  return _localizedRouteScheduleEntryLabel(
    locale,
    trip: trip,
    entry: entry,
    includeLegDirection: false,
    allowMeeting: false,
  );
}

String localizedGroupScheduleEntryLabel(
  Locale locale, {
  required Trip trip,
  required ScheduleEntry entry,
}) {
  if (trip.isSolo) {
    throw StateError(
      'localizedGroupScheduleEntryLabel requires a group trip: tripId=${trip.id}',
    );
  }
  return _localizedRouteScheduleEntryLabel(
    locale,
    trip: trip,
    entry: entry,
    includeLegDirection: true,
    allowMeeting: true,
  );
}

String localizedGroupScheduleEntryDescription(
  Locale locale, {
  required Trip trip,
  required ScheduleEntry entry,
}) {
  if (trip.isSolo) {
    throw StateError(
      'localizedGroupScheduleEntryDescription requires a group trip: '
      'tripId=${trip.id}',
    );
  }
  if (entry.generatedBy != ScheduleEntrySource.route ||
      !isEnglishTransitLocale(locale)) {
    return entry.description;
  }

  final l10n = lookupAppLocalizations(locale);
  return switch (entry.itemKind) {
    ScheduleEntryKind.meeting => l10n.navMeetingActionMain,
    ScheduleEntryKind.goal => l10n.navTripEndedSub,
    _ => entry.description,
  };
}

String _localizedRouteScheduleEntryLabel(
  Locale locale, {
  required Trip trip,
  required ScheduleEntry entry,
  required bool includeLegDirection,
  required bool allowMeeting,
}) {
  if (entry.generatedBy != ScheduleEntrySource.route) {
    return entry.label;
  }
  if (!isEnglishTransitLocale(locale)) {
    return normalizeJapaneseTransitDisplayText(entry.label);
  }

  final l10n = lookupAppLocalizations(locale);
  final prefix = includeLegDirection
      ? _localizedGroupLegPrefix(trip, entry)
      : '';

  if (entry.itemKind == ScheduleEntryKind.meeting) {
    if (!allowMeeting) {
      throw StateError(
        'Solo route schedule must not contain a group meeting entry: '
        'entryId=${entry.id}',
      );
    }
    final candidate = _candidateForScheduleLeg(trip, entry);
    if (candidate.steps.isEmpty) {
      throw StateError(
        'Meeting schedule entry requires route steps: entryId=${entry.id}',
      );
    }
    final first = candidate.steps.first;
    final place = _localizedEndpoint(
      locale,
      japanese: candidate.originName ?? first.fromName,
      english: candidate.originNameEn ?? first.fromNameEn,
      field: 'origin_name_en',
      identity: 'candidateId=${candidate.id}',
    );
    return '$prefix${l10n.categoryMeeting}: $place';
  }

  if (entry.itemKind == ScheduleEntryKind.goal) {
    return '$prefix${_localizedGoalLabel(locale, trip: trip, entry: entry)}';
  }

  final stepId = entry.routeStepId;
  if (stepId == null || stepId.isEmpty) {
    throw StateError(
      'Route schedule entry is missing routeStepId: '
      'entryId=${entry.id}, kind=${entry.itemKind.name}',
    );
  }

  final step = trip.stepsById[stepId];
  if (step == null) {
    throw StateError(
      'Route schedule entry references an unknown step: '
      'entryId=${entry.id}, routeStepId=$stepId',
    );
  }

  switch (entry.routeRole) {
    case 'walk':
      final destination = _localizedEndpoint(
        locale,
        japanese: step.toName,
        english: step.toNameEn,
        field: 'to_en',
        identity: 'stepId=${step.stepId}',
      );
      final duration = step.minutes > 0
          ? ' (${l10n.minutesValue(step.minutes)})'
          : '';
      return '$prefix${l10n.scheduleWalkTo(destination, duration)}';
    case 'ride':
      if (!step.isRide) {
        throw StateError(
          'ride schedule entry points to a non-ride step: '
          'entryId=${entry.id}, kind=${step.kind}',
        );
      }
      return '$prefix${localizedRideTitle(locale, step)} · '
          '${l10n.scheduleBoardAt(localizedRideFromName(locale, step))}';
    case 'arrival':
      if (!step.isRide) {
        throw StateError(
          'arrival schedule entry points to a non-ride step: '
          'entryId=${entry.id}, kind=${step.kind}',
        );
      }
      return '$prefix${localizedRideTitle(locale, step)} · '
          '${l10n.scheduleArriveAt(localizedRideToName(locale, step))}';
    case 'wait_start':
      final japanese = step.place ?? step.fromName;
      final english = step.placeEn ?? step.fromNameEn;
      final place = _localizedEndpoint(
        locale,
        japanese: japanese,
        english: english,
        field: 'place_en',
        identity: 'stepId=${step.stepId}',
      );
      final duration = step.minutes > 0
          ? ' (${l10n.minutesValue(step.minutes)})'
          : '';
      return '$prefix${l10n.waitAt(place)}$duration';
    case null:
      throw StateError(
        'Route schedule entry is missing routeRole: '
        'entryId=${entry.id}, routeStepId=$stepId',
      );
    default:
      throw StateError(
        'Unsupported route schedule role: '
        'entryId=${entry.id}, routeRole=${entry.routeRole}',
      );
  }
}

Candidate _candidateForScheduleLeg(Trip trip, ScheduleEntry entry) {
  final legIndex = entry.legIndex;
  if (legIndex < 0 || legIndex >= trip.legs.length) {
    throw StateError(
      'Schedule entry has invalid legIndex: '
      'entryId=${entry.id}, legIndex=$legIndex, legs=${trip.legs.length}',
    );
  }
  return trip.legs[legIndex].candidate;
}

String _localizedGroupLegPrefix(Trip trip, ScheduleEntry entry) {
  final legIndex = entry.legIndex;
  if (legIndex < 0 || legIndex >= trip.legs.length) {
    throw StateError(
      'Schedule entry has invalid legIndex: '
      'entryId=${entry.id}, legIndex=$legIndex, legs=${trip.legs.length}',
    );
  }
  return switch (trip.legs[legIndex].direction) {
    LegDirection.outbound => '➡️ ',
    LegDirection.inbound => '⬅️ ',
    LegDirection.other || LegDirection.unknown => '',
  };
}

String localizedSoloScheduleEntryCompactLabel(
  Locale locale, {
  required Trip trip,
  required ScheduleEntry entry,
}) {
  if (!isEnglishTransitLocale(locale)) {
    return localizedSoloScheduleEntryLabel(locale, trip: trip, entry: entry);
  }
  if (!trip.isSolo) {
    throw StateError(
      'localizedSoloScheduleEntryCompactLabel requires a solo trip: '
      'tripId=${trip.id}',
    );
  }
  if (entry.generatedBy != ScheduleEntrySource.route) {
    return entry.label;
  }

  String compactPlace({
    required String? japanese,
    required String? english,
    required String field,
    required String identity,
    required bool requireEnglish,
  }) {
    final normalizedJapanese = japanese?.trim();
    if (normalizedJapanese == null || normalizedJapanese.isEmpty) {
      throw StateError('Route endpoint is missing: field=$field $identity');
    }

    final normalizedEnglish = english?.trim();
    if (normalizedEnglish == null || normalizedEnglish.isEmpty) {
      if (requireEnglish) {
        throw StateError(
          'Official English transit name is missing: '
          'field=$field $identity',
        );
      }
      return normalizedJapanese;
    }
    if (normalizedEnglish == normalizedJapanese) return normalizedEnglish;
    return '$normalizedEnglish\n$normalizedJapanese';
  }

  String compactGoal() {
    final legIndex = entry.legIndex;
    if (legIndex < 0 || legIndex >= trip.legs.length) {
      throw StateError(
        'Goal schedule entry has invalid legIndex: '
        'entryId=${entry.id}, legIndex=$legIndex, legs=${trip.legs.length}',
      );
    }
    final candidate = trip.legs[legIndex].candidate;
    if (candidate.steps.isEmpty) {
      throw StateError(
        'Goal schedule entry requires route steps: entryId=${entry.id}',
      );
    }
    final last = candidate.steps.last;
    return compactPlace(
      japanese: candidate.destinationName ?? last.toName,
      english: candidate.destinationNameEn ?? last.toNameEn,
      field: 'destination_name_en',
      identity: 'candidateId=${candidate.id}',
      requireEnglish: false,
    );
  }

  final stepId = entry.routeStepId;
  if (stepId == null || stepId.isEmpty) {
    if (entry.itemKind == ScheduleEntryKind.goal) {
      return compactGoal();
    }
    throw StateError(
      'English route schedule entry is missing routeStepId: '
      'entryId=${entry.id}, kind=${entry.itemKind.name}',
    );
  }

  final step = trip.stepsById[stepId];
  if (step == null) {
    throw StateError(
      'English route schedule entry references an unknown step: '
      'entryId=${entry.id}, routeStepId=$stepId',
    );
  }

  switch (entry.routeRole) {
    case 'walk':
      final destination = compactPlace(
        japanese: step.toName,
        english: step.toNameEn,
        field: 'to_en',
        identity: 'stepId=${step.stepId}',
        requireEnglish: false,
      );
      if (step.minutes <= 0) return destination;
      return '$destination\n'
          '${lookupAppLocalizations(locale).minutesValue(step.minutes)}';
    case 'ride':
      if (!step.isRide) {
        throw StateError(
          'ride schedule entry points to a non-ride step: '
          'entryId=${entry.id}, kind=${step.kind}',
        );
      }
      final routeTitle = localizedRideTitle(locale, step);
      final boardingPlace = compactPlace(
        japanese: step.fromName,
        english: step.fromNameEn,
        field: 'from_en',
        identity: 'stepId=${step.stepId}',
        requireEnglish: true,
      );
      return '$routeTitle\n$boardingPlace';
    case 'arrival':
      if (!step.isRide) {
        throw StateError(
          'arrival schedule entry points to a non-ride step: '
          'entryId=${entry.id}, kind=${step.kind}',
        );
      }
      return compactPlace(
        japanese: step.toName,
        english: step.toNameEn,
        field: 'to_en',
        identity: 'stepId=${step.stepId}',
        requireEnglish: true,
      );
    case 'wait_start':
      return compactPlace(
        japanese: step.place ?? step.fromName,
        english: step.placeEn ?? step.fromNameEn,
        field: 'place_en',
        identity: 'stepId=${step.stepId}',
        requireEnglish: false,
      );
    case null:
      throw StateError(
        'English route schedule entry is missing routeRole: '
        'entryId=${entry.id}, routeStepId=$stepId',
      );
    default:
      throw StateError(
        'Unsupported English route schedule role: '
        'entryId=${entry.id}, routeRole=${entry.routeRole}',
      );
  }
}

String _localizedGoalLabel(
  Locale locale, {
  required Trip trip,
  required ScheduleEntry entry,
}) {
  final legIndex = entry.legIndex;
  if (legIndex < 0 || legIndex >= trip.legs.length) {
    throw StateError(
      'Goal schedule entry has invalid legIndex: '
      'entryId=${entry.id}, legIndex=$legIndex, legs=${trip.legs.length}',
    );
  }
  final candidate = trip.legs[legIndex].candidate;
  if (candidate.steps.isEmpty) {
    throw StateError(
      'Goal schedule entry requires route steps: entryId=${entry.id}',
    );
  }
  final last = candidate.steps.last;
  final destination = _localizedEndpoint(
    locale,
    japanese: candidate.destinationName ?? last.toName,
    english: candidate.destinationNameEn ?? last.toNameEn,
    field: 'destination_name_en',
    identity: 'candidateId=${candidate.id}',
  );
  return lookupAppLocalizations(locale).scheduleArriveAt(destination);
}

String _localizedEndpoint(
  Locale locale, {
  required String? japanese,
  required String? english,
  required String field,
  required String identity,
}) {
  final normalizedJapanese = japanese?.trim();
  if (normalizedJapanese == null || normalizedJapanese.isEmpty) {
    throw StateError('Route endpoint is missing: field=$field $identity');
  }
  if (!isEnglishTransitLocale(locale)) return normalizedJapanese;

  final normalizedEnglish = english?.trim();
  if (normalizedEnglish == null || normalizedEnglish.isEmpty) {
    return normalizedJapanese;
  }
  if (normalizedEnglish == normalizedJapanese) return normalizedEnglish;
  return '$normalizedEnglish ($normalizedJapanese)';
}
