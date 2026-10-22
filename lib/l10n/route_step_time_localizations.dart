import '../models/route_models.dart';
import 'app_localizations.dart';

/// Uses the route's scheduled clocks without estimating from its duration.
String routeStepTimeLabel(StepSeg segment, AppLocalizations l10n) {
  final departure = segment.departureTime?.trim() ?? '';
  final arrival = segment.arrivalTime?.trim() ?? '';
  if (departure.isNotEmpty && arrival.isNotEmpty) {
    return '$departure → $arrival';
  }
  if (departure.isNotEmpty) return l10n.segmentDepartureAt(departure);
  if (arrival.isNotEmpty) return l10n.segmentArrivalAt(arrival);
  return l10n.replanUnknownTime;
}
