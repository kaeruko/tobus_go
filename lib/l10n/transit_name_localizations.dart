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
  if (!isEnglishTransitLocale(locale)) return value;
  return _requiredEnglish(
    step.fromNameEn,
    field: 'from_en',
    identity: 'stepId=${step.stepId}',
  );
}

String localizedRideToName(Locale locale, StepSeg step) {
  final value = step.toName?.trim();
  if (value == null || value.isEmpty) {
    throw StateError('Ride step has no destination: stepId=${step.stepId}');
  }
  if (!isEnglishTransitLocale(locale)) return value;
  return _requiredEnglish(
    step.toNameEn,
    field: 'to_en',
    identity: 'stepId=${step.stepId}',
  );
}

String localizedStopName(Locale locale, StopPoint stop) {
  final value = stop.name.trim();
  if (value.isEmpty) {
    throw StateError('Transit stop has an empty name: stopId=${stop.stopId}');
  }
  if (!isEnglishTransitLocale(locale)) return value;
  return _requiredEnglish(
    stop.nameEn,
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
  if (!isEnglishTransitLocale(locale)) return japanese;
  return _requiredEnglish(english, field: field, identity: identity);
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
