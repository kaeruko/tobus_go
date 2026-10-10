import '../models/route_models.dart';
import '../utils/stop_map_utils.dart';

/// One genuine transfer: an arrival ride, a walk, optional waiting, then a ride.
/// Other walks (journey origin/destination, sightseeing, etc.) are not transfers.
class TransferWalkDetails {
  final StepSeg arrivingRide;
  final StepSeg walkingStep;
  final StepSeg? waitingStep;
  final StepSeg departingRide;
  final StopPoint alightingStop;
  final StopPoint boardingStop;
  final String alightingTime;
  final String boardingTime;
  final int transferMinutes;

  const TransferWalkDetails._({
    required this.arrivingRide,
    required this.walkingStep,
    required this.waitingStep,
    required this.departingRide,
    required this.alightingStop,
    required this.boardingStop,
    required this.alightingTime,
    required this.boardingTime,
    required this.transferMinutes,
  });

  static final RegExp _clockPattern = RegExp(r'^(\d{2}):(\d{2})$');

  static int _clockMinute(String? clock, String field, StepSeg step) {
    final match = clock == null ? null : _clockPattern.firstMatch(clock);
    if (match == null) {
      throw StateError(
        'Transfer needs a scheduled $field HH:mm: '
        'stepId=${step.stepId} value=$clock',
      );
    }
    final hour = int.parse(match.group(1)!);
    final minute = int.parse(match.group(2)!);
    if (hour > 47 || minute > 59) {
      throw StateError(
        'Transfer $field is invalid: stepId=${step.stepId} value=$clock',
      );
    }
    return hour * 60 + minute;
  }

  /// Null means this is not a ride-to-ride transfer.
  /// Incomplete transfer coordinates/clocks fail loudly rather than inventing a
  /// map pin, time, or substitute stop.
  static TransferWalkDetails? forStep(List<StepSeg> steps, int stepIndex) {
    RangeError.checkValidIndex(stepIndex, steps, 'stepIndex');
    var walkIndex = stepIndex;
    if (steps[stepIndex].kind == 'wait') {
      if (stepIndex == 0 || steps[stepIndex - 1].kind != 'walk') {
        return null;
      }
      walkIndex = stepIndex - 1;
    } else if (steps[stepIndex].kind != 'walk') {
      return null;
    }

    if (walkIndex == 0) return null;
    // Some routes have a waiting step directly after alighting, before the
    // short transfer walk. It still belongs to the same ride-to-ride transfer.
    var arrivingIndex = walkIndex - 1;
    if (steps[arrivingIndex].kind == 'wait') {
      arrivingIndex--;
    }
    if (arrivingIndex < 0) return null;
    final arriving = steps[arrivingIndex];
    if (!arriving.isRide) return null;

    var nextIndex = walkIndex + 1;
    StepSeg? waiting;
    if (nextIndex < steps.length && steps[nextIndex].kind == 'wait') {
      waiting = steps[nextIndex];
      nextIndex++;
    }
    if (nextIndex >= steps.length || !steps[nextIndex].isRide) return null;
    final departing = steps[nextIndex];
    final walking = steps[walkIndex];
    if (arriving.stops.isEmpty || departing.stops.isEmpty) {
      throw StateError(
        'Transfer ride has no boarding/alighting stop points: '
        'arrival=${arriving.stepId} departure=${departing.stepId}',
      );
    }
    final alightStop = arriving.stops.last;
    final boardStop = departing.stops.first;
    for (final stop in [alightStop, boardStop]) {
      if (!hasUsableTransitCoordinate(stop.lat, stop.lon)) {
        throw StateError(
          'Transfer stop has no usable coordinate: '
          'stop=${stop.name} stopId=${stop.stopId} '
          'lat=${stop.lat} lon=${stop.lon}',
        );
      }
    }
    if (alightStop.name.trim().isEmpty || boardStop.name.trim().isEmpty) {
      throw StateError(
        'Transfer stop name is missing: '
        'arrival=${arriving.stepId} departure=${departing.stepId}',
      );
    }
    if (walking.minutes < 0 || (waiting != null && waiting.minutes < 0)) {
      throw StateError(
        'Transfer walk/wait duration cannot be negative: '
        'walk=${walking.stepId} wait=${waiting?.stepId}',
      );
    }

    final arrivalClock = _clockMinute(
      arriving.arrivalTime, 'arrival_time', arriving,
    );
    final departureClock = _clockMinute(
      departing.departureTime, 'departure_time', departing,
    );
    // The API uses local HH:mm display clocks. Permit midnight rollover
    // without assuming UTC or constructing a date from unrelated metadata.
    final delta = (departureClock - arrivalClock) % (24 * 60);
    if (delta < walking.minutes) {
      throw StateError(
        'Transfer duration is shorter than walking time: '
        'arrival=${arriving.arrivalTime} departure=${departing.departureTime} '
        'walkMinutes=${walking.minutes}',
      );
    }

    return TransferWalkDetails._(
      arrivingRide: arriving,
      walkingStep: walking,
      waitingStep: waiting,
      departingRide: departing,
      alightingStop: alightStop,
      boardingStop: boardStop,
      alightingTime: arriving.arrivalTime!,
      boardingTime: departing.departureTime!,
      transferMinutes: delta,
    );
  }
}
