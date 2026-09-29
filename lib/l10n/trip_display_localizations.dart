import 'package:flutter/widgets.dart';

import '../models/group_models.dart';
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

String localizedSoloScheduleEntryLabel(
  Locale locale, {
  required Trip trip,
  required ScheduleEntry entry,
}) {
  if (!isEnglishTransitLocale(locale)) return entry.label;
  if (!trip.isSolo) {
    throw StateError(
      'localizedSoloScheduleEntryLabel requires a solo trip: tripId=${trip.id}',
    );
  }
  if (entry.generatedBy != ScheduleEntrySource.route) {
    return entry.label;
  }

  final stepId = entry.routeStepId;
  if (stepId == null || stepId.isEmpty) {
    if (entry.itemKind == ScheduleEntryKind.goal) {
      return _localizedGoalLabel(locale, trip: trip, entry: entry);
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

  final l10n = lookupAppLocalizations(locale);
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
      return l10n.scheduleWalkTo(destination, duration);
    case 'ride':
      if (!step.isRide) {
        throw StateError(
          'ride schedule entry points to a non-ride step: '
          'entryId=${entry.id}, kind=${step.kind}',
        );
      }
      return '${localizedRideTitle(locale, step)} · '
          '${l10n.scheduleBoardAt(localizedRideFromName(locale, step))}';
    case 'arrival':
      if (!step.isRide) {
        throw StateError(
          'arrival schedule entry points to a non-ride step: '
          'entryId=${entry.id}, kind=${step.kind}',
        );
      }
      return '${localizedRideTitle(locale, step)} · '
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
      return l10n.waitAt(place);
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
