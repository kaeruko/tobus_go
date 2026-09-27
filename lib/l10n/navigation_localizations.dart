import 'package:flutter/widgets.dart';

import '../logic/trip_navigator.dart';
import 'app_localizations.dart';

String localizedNavigationText(
  AppLocalizations l10n,
  Locale locale,
  NavigationTextToken? token, {
  required String fallback,
}) {
  if (token == null) return fallback;

  String stringArg(String name) {
    final value = token.args[name];
    if (value is! String) {
      throw StateError(
        'Navigation text token ${token.key.name} requires String $name',
      );
    }
    return value;
  }

  String transitArg(String name) {
    final japanese = stringArg(name);
    if (locale.languageCode != 'en') return japanese;
    final english = token.args['${name}En'];
    if (english is! String || english.trim().isEmpty) {
      throw StateError(
        'Navigation text token ${token.key.name} requires official English '
        'transit text ${name}En',
      );
    }
    return english.trim();
  }

  String freeformArg(String name) {
    final original = stringArg(name);
    if (locale.languageCode != 'en') return original;
    final english = token.args['${name}En'];
    if (english == null) return original;
    if (english is! String || english.trim().isEmpty) {
      throw StateError(
        'Navigation text token ${token.key.name} has invalid optional '
        'English text ${name}En',
      );
    }
    return english.trim();
  }

  int intArg(String name) {
    final value = token.args[name];
    if (value is! int) {
      throw StateError(
        'Navigation text token ${token.key.name} requires int $name',
      );
    }
    return value;
  }

  double doubleArg(String name) {
    final value = token.args[name];
    if (value is! num) {
      throw StateError(
        'Navigation text token ${token.key.name} requires num $name',
      );
    }
    return value.toDouble();
  }

  bool boolArg(String name) {
    final value = token.args[name];
    if (value is! bool) {
      throw StateError(
        'Navigation text token ${token.key.name} requires bool $name',
      );
    }
    return value;
  }

  switch (token.key) {
    case NavigationTextKey.idleStatus:
      return l10n.navIdleStatus;
    case NavigationTextKey.busRideStatus:
      return l10n.navBusRideStatus;
    case NavigationTextKey.railRideStatus:
      return l10n.navRailRideStatus;
    case NavigationTextKey.rideArrivalSummary:
      return l10n.navRideArrivalSummary(
        stringArg('arrivalTime'),
        transitArg('rideTitle'),
        transitArg('destination'),
      );
    case NavigationTextKey.preDepartureMain:
      return l10n.navPreDepartureMain;
    case NavigationTextKey.plannedDepartureSub:
      return l10n.navPlannedDepartureSub(stringArg('time'));
    case NavigationTextKey.preStartStatus:
      return l10n.navPreStartStatus;
    case NavigationTextKey.startsInSub:
      return l10n.navStartsInSub(intArg('hours'), intArg('minutes'));
    case NavigationTextKey.movingStatus:
      return l10n.navMovingStatus;
    case NavigationTextKey.meetingDefaultSub:
      return l10n.navMeetingDefaultSub;
    case NavigationTextKey.meetingStatus:
      return l10n.navMeetingStatus;
    case NavigationTextKey.arrivedDefaultSub:
      return l10n.navArrivedDefaultSub;
    case NavigationTextKey.arrivedStatus:
      return l10n.navArrivedStatus;
    case NavigationTextKey.waitingDefaultSub:
      return l10n.navWaitingDefaultSub;
    case NavigationTextKey.waitingStatus:
      return l10n.navWaitingStatus;
    case NavigationTextKey.walkHeadingMain:
      return l10n.navWalkHeadingMain(freeformArg('destination'));
    case NavigationTextKey.walkDistanceSub:
      return l10n.navWalkDistanceSub(doubleArg('meters'));
    case NavigationTextKey.positionCheckingMain:
      return l10n.navPositionCheckingMain(transitArg('rideTitle'));
    case NavigationTextKey.busWaitingMain:
      return l10n.navBusWaitingMain;
    case NavigationTextKey.positionCheckingSub:
      return l10n.navPositionCheckingSub;
    case NavigationTextKey.busPositionCheckingAtStopSub:
      return l10n.navBusPositionCheckingAtStopSub(transitArg('stopName'));
    case NavigationTextKey.waitingToBoardStatus:
      return l10n.navWaitingToBoardStatus;
    case NavigationTextKey.searchingStatus:
      return l10n.navSearchingStatus;
    case NavigationTextKey.approachingBusMain:
      return l10n.navApproachingBusMain(
        transitArg('rideTitle'),
        intArg('count'),
      );
    case NavigationTextKey.approachingRailMain:
      return l10n.navApproachingRailMain(
        transitArg('rideTitle'),
        intArg('count'),
      );
    case NavigationTextKey.nowAtSub:
      return l10n.navNowAtSub(transitArg('placeName'));
    case NavigationTextKey.arrivedMain:
      return l10n.navArrivedMain;
    case NavigationTextKey.getOffNextMain:
      return l10n.navGetOffNextMain;
    case NavigationTextKey.rideCurrentPlaceMain:
      return l10n.navRideCurrentPlaceMain(
        transitArg('rideTitle'),
        transitArg('placeName'),
      );
    case NavigationTextKey.transitPlace:
      return transitArg('placeName');
    case NavigationTextKey.staleBusNotice:
      final placeKind = stringArg('placeKind');
      final rawPlace = stringArg('place');
      final place = switch (placeKind) {
        'name' => locale.languageCode == 'en'
            ? transitArg('place')
            : rawPlace,
        'id' => l10n.navStopId(rawPlace),
        'unknown' => l10n.navUnknownStop,
        _ => throw StateError(
            'Unsupported stale bus place kind: $placeKind',
          ),
      };
      final movementText = boolArg('moving')
          ? l10n.navMovingToward(place)
          : place;
      return l10n.navStaleBusNotice(
        movementText,
        intArg('ageMinutes'),
      );
    case NavigationTextKey.staleRailNotice:
      final rawPlace = stringArg('placeName');
      final place = rawPlace.isEmpty
          ? l10n.navUnknownStation
          : transitArg('placeName');
      return l10n.navStaleRailNotice(place, intArg('ageMinutes'));
    case NavigationTextKey.tripEndedMain:
      return l10n.navTripEndedMain;
    case NavigationTextKey.tripEndedSub:
      return l10n.navTripEndedSub;
    case NavigationTextKey.tripEndedStatus:
      return l10n.navTripEndedStatus;
    case NavigationTextKey.tripCancelledMain:
      return l10n.navTripCancelledMain;
    case NavigationTextKey.tripCancelledSub:
      return l10n.navTripCancelledSub;
    case NavigationTextKey.tripCancelledStatus:
      return l10n.navTripCancelledStatus;
    case NavigationTextKey.departureCountdownMain:
      return l10n.navDepartureCountdownMain(
        stringArg('leaveTime'),
        intArg('minutes'),
      );
    case NavigationTextKey.boardingSub:
      return l10n.navBoardingSub(
        stringArg('rideTime'),
        transitArg('routeTitle'),
      );
    case NavigationTextKey.boardingPlannedSub:
      return l10n.navBoardingPlannedSub(
        stringArg('rideTime'),
        transitArg('routeTitle'),
      );
    case NavigationTextKey.walkToRideCountdownMain:
      return l10n.navWalkToRideCountdownMain(
        stringArg('rideTime'),
        transitArg('destination'),
        intArg('minutes'),
      );
    case NavigationTextKey.realtimeUnavailableNotice:
      return l10n.navRealtimeUnavailableNotice;
  }
}
