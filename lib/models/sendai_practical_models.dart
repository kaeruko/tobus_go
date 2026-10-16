/// Isolated test schema; never reinterpret these clocks as exact arrivals.
class SendaiClock {
  final String date;
  final String time;
  final String basis;
  final int minuteNumerator;
  final int minuteDenominator;

  const SendaiClock(this.date, this.time, this.basis,
      this.minuteNumerator, this.minuteDenominator);

  factory SendaiClock.fromJson(Map<String, dynamic> json) {
    final minute = json['minute'] as Map<String, dynamic>;
    if (json['actual_arrival_verified'] != false ||
        (minute['denominator'] as int) <= 0) {
      throw const FormatException('Unrecognized scheduled clock');
    }
    return SendaiClock(json['date'] as String, json['time'] as String,
        json['basis'] as String, minute['numerator'] as int,
        minute['denominator'] as int);
  }
}

class SendaiStop {
  final String id;
  final String name;
  final String mode;
  const SendaiStop(this.id, this.name, this.mode);
  factory SendaiStop.fromJson(Map<String, dynamic> json) => SendaiStop(
      json['id'] as String, json['name'] as String, json['mode'] as String);
}

class SendaiPracticalCapabilities {
  final List<SendaiStop> stops;
  final List<String> supportedModes;
  final List<String> unsupported;
  final List<String> operatingDates;

  const SendaiPracticalCapabilities(
      this.stops, this.supportedModes, this.unsupported, this.operatingDates);

  factory SendaiPracticalCapabilities.fromJson(Map<String, dynamic> json) {
    if (json['schema'] != 'sendai_practical_route_v1' ||
        json['environment'] != 'test' || json['city'] != 'sendai' ||
        json['actual_connection_guaranteed'] != false ||
        json['experimental_margin_formally_adopted'] != false ||
        !(json['fare_policy_ids'] as List).contains('sendai_fureai_pass')) {
      throw const FormatException('Reviewed Sendai test capabilities required');
    }
    return SendaiPracticalCapabilities(
        (json['stops'] as List).map((s) => SendaiStop.fromJson(s as Map<String, dynamic>)).toList(),
        List<String>.from(json['supported_modes'] as List),
        List<String>.from(json['unsupported'] as List),
        List<String>.from(json['operating_dates'] as List));
  }
}

sealed class SendaiPracticalEvent {
  const SendaiPracticalEvent();
  factory SendaiPracticalEvent.fromJson(Map<String, dynamic> json) {
    switch (json['kind']) {
      case 'ride':
        return SendaiPracticalRide.fromJson(json);
      case 'standard_transfer':
        return SendaiPracticalTransfer.fromJson(json);
      default:
        throw const FormatException('Unsupported Sendai test event');
    }
  }
}

class SendaiPracticalRide extends SendaiPracticalEvent {
  final String mode;
  final String tripId;
  final String fromStopId;
  final String toStopId;
  final SendaiClock departure;
  final SendaiClock arrival;

  const SendaiPracticalRide(this.mode, this.tripId, this.fromStopId,
      this.toStopId, this.departure, this.arrival);

  factory SendaiPracticalRide.fromJson(Map<String, dynamic> json) {
    final mode = json['mode'] as String;
    final departure = SendaiClock.fromJson(json['departure'] as Map<String, dynamic>);
    final arrival = SendaiClock.fromJson(json['arrival'] as Map<String, dynamic>);
    if ((mode == 'rail' && (departure.basis != 'published_departure_minute' ||
            arrival.basis != 'published_clock_arrival_proxy')) ||
        (mode == 'bus' && (departure.basis != 'gtfs_scheduled_departure' ||
            arrival.basis != 'gtfs_scheduled_arrival')) ||
        (mode != 'rail' && mode != 'bus')) {
      throw const FormatException('Unknown Sendai ride clock semantics');
    }
    return SendaiPracticalRide(mode, json['trip_id'] as String,
        json['from_stop_id'] as String, json['to_stop_id'] as String,
        departure, arrival);
  }
}

class SendaiPracticalTransfer extends SendaiPracticalEvent {
  final int standardMinutes;
  final int marginMinutes;
  final String timeBasis;
  final String? pathDescription;
  final SendaiClock ready;

  const SendaiPracticalTransfer(this.standardMinutes, this.marginMinutes,
      this.timeBasis, this.pathDescription, this.ready);

  factory SendaiPracticalTransfer.fromJson(Map<String, dynamic> json) {
    if (json['walking_time_measured'] != false ||
        json['connection_guaranteed'] != false ||
        json['margin_status'] != 'experimental_unvalidated' ||
        !['official_standard', 'experimental_planning_assumption'].contains(json['time_basis'])) {
      throw const FormatException('Unverified transfer must remain explicit');
    }
    return SendaiPracticalTransfer(json['standard_minutes'] as int,
        json['margin_minutes'] as int, json['time_basis'] as String,
        json['path_description'] as String?,
        SendaiClock.fromJson(json['ready'] as Map<String, dynamic>));
  }
}

class SendaiPracticalCandidate {
  final SendaiClock arrival;
  final List<SendaiPracticalEvent> events;

  const SendaiPracticalCandidate(this.arrival, this.events);

  factory SendaiPracticalCandidate.fromJson(Map<String, dynamic> json) {
    final fare = json['fare'] as Map<String, dynamic>;
    if (json['schema'] != 'sendai_practical_route_v1' ||
        json['profile'] != 'sendai_published_minute_v1' ||
        json['exact_arrival_verified'] != false ||
        json['actual_connection_guaranteed'] != false ||
        json['experimental_margin_formally_adopted'] != false ||
        fare['policy_id'] != 'sendai_fureai_pass' ||
        fare['additional_payment_yen'] != 0) {
      throw const FormatException('Expected explicit free-pass scheduled model');
    }
    return SendaiPracticalCandidate(
        SendaiClock.fromJson(json['arrival'] as Map<String, dynamic>),
        (json['events'] as List).map((e) => SendaiPracticalEvent.fromJson(e as Map<String, dynamic>)).toList());
  }
}
