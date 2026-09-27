import 'package:flutter/widgets.dart';

import '../models/route_models.dart';

bool isEnglishTransitLocale(Locale locale) => locale.languageCode == 'en';

String _requiredEnglish(
  String? value, {
  required String field,
  required String identity,
}) {
  final normalized = value?.trim();
  if (normalized == null || normalized.isEmpty) {
    throw StateError(
      'Official English transit name is missing: field=$field $identity',
    );
  }
  return normalized;
}

String localizedTransitName(
  Locale locale, {
  required String japanese,
  required String? english,
  required String field,
  required String identity,
}) {
  final normalizedJapanese = japanese.trim();
  if (normalizedJapanese.isEmpty) {
    throw StateError('Transit name is empty: field=$field $identity');
  }
  if (!isEnglishTransitLocale(locale)) return normalizedJapanese;

  final normalizedEnglish = _requiredEnglish(
    english,
    field: field,
    identity: identity,
  );
  if (normalizedEnglish == normalizedJapanese) return normalizedEnglish;
  return '$normalizedEnglish ($normalizedJapanese)';
}

String localizedOptionalPlaceName(
  Locale locale, {
  required String japanese,
  required String? english,
  required String field,
  required String identity,
}) {
  final normalizedJapanese = japanese.trim();
  if (normalizedJapanese.isEmpty) {
    throw StateError('Place name is empty: field=$field $identity');
  }
  if (!isEnglishTransitLocale(locale)) return normalizedJapanese;

  if (english == null) return normalizedJapanese;
  final normalizedEnglish = english.trim();
  if (normalizedEnglish.isEmpty) {
    throw StateError(
      'Optional English place name is blank: field=$field $identity',
    );
  }
  if (normalizedEnglish == normalizedJapanese) return normalizedEnglish;
  return '$normalizedEnglish ($normalizedJapanese)';
}

String localizedRideTitle(Locale locale, StepSeg step) {
  if (!step.isRide) {
    throw StateError(
      'localizedRideTitle requires a ride step: '
      'stepId=${step.stepId}, kind=${step.kind}',
    );
  }
  if (!isEnglishTransitLocale(locale)) return step.title;
  return _requiredEnglish(
    step.titleEn,
    field: 'title_en',
    identity: 'stepId=${step.stepId}',
  );
}

String localizedRideFromName(Locale locale, StepSeg step) {
  final value = step.fromName?.trim();
  if (value == null || value.isEmpty) {
    throw StateError('Ride step has no origin: stepId=${step.stepId}');
  }
  return localizedTransitName(
    locale,
    japanese: value,
    english: step.fromNameEn,
    field: 'from_en',
    identity: 'stepId=${step.stepId}',
  );
}

String localizedRideToName(Locale locale, StepSeg step) {
  final value = step.toName?.trim();
  if (value == null || value.isEmpty) {
    throw StateError('Ride step has no destination: stepId=${step.stepId}');
  }
  return localizedTransitName(
    locale,
    japanese: value,
    english: step.toNameEn,
    field: 'to_en',
    identity: 'stepId=${step.stepId}',
  );
}

String? localizedStepEndpointName(
  Locale locale,
  StepSeg step, {
  required bool origin,
}) {
  if (step.isRide) {
    return origin
        ? localizedRideFromName(locale, step)
        : localizedRideToName(locale, step);
  }

  final japanese = (origin ? step.fromName : step.toName)?.trim();
  if (japanese == null || japanese.isEmpty) return null;

  switch (step.kind) {
    case 'wait':
      return localizedTransitName(
        locale,
        japanese: japanese,
        english: origin ? step.fromNameEn : step.toNameEn,
        field: origin ? 'from_en' : 'to_en',
        identity: 'stepId=${step.stepId}',
      );
    case 'walk':
      return localizedOptionalPlaceName(
        locale,
        japanese: japanese,
        english: origin ? step.fromNameEn : step.toNameEn,
        field: origin ? 'walk_from_en' : 'walk_to_en',
        identity: 'stepId=${step.stepId}',
      );
    default:
      throw StateError(
        'Unsupported route endpoint step kind: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
  }
}

String localizedStopName(Locale locale, StopPoint stop) {
  final value = stop.name.trim();
  if (value.isEmpty) {
    throw StateError('Transit stop has an empty name: stopId=${stop.stopId}');
  }
  return localizedTransitName(
    locale,
    japanese: value,
    english: stop.nameEn,
    field: 'name_en',
    identity: 'stopId=${stop.stopId ?? '<unknown>'}',
  );
}

String localizedOptionalTransitName(
  Locale locale, {
  required String japanese,
  required String? english,
  required String field,
  required String identity,
}) {
  return localizedTransitName(
    locale,
    japanese: japanese,
    english: english,
    field: field,
    identity: identity,
  );
}

List<String> localizedCandidateLines(Locale locale, Candidate candidate) {
  if (!isEnglishTransitLocale(locale)) return candidate.lines;

  final lines = <String>[];
  for (final step in candidate.steps) {
    if (!step.isRide) continue;
    final title = localizedRideTitle(locale, step);
    if (!lines.contains(title)) lines.add(title);
  }
  if (candidate.rides > 0 && lines.isEmpty) {
    throw StateError(
      'English route line summary has no ride labels: candidate=${candidate.id}',
    );
  }
  return lines;
}
