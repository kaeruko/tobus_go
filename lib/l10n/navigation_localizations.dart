import 'package:flutter/widgets.dart';

import '../logic/trip_navigator.dart';
import 'app_localizations.dart';
import 'transit_name_localizations.dart';

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

  String officialTransitArg(String name) {
    final japanese = stringArg(name);
    if (!isEnglishTransitLocale(locale)) return japanese;
    final english = token.args['${name}En'];
    if (english is! String || english.trim().isEmpty) {
      throw StateError(
        'Navigation text token ${token.key.name} requires official English '
        'transit text ${name}En',
      );
    }
    return english.trim();
  }

  String transitPlaceArg(String name) {
    final japanese = stringArg(name);
    if (!isEnglishTransitLocale(locale)) return japanese;
    final english = token.args['${name}En'];
    if (english is! String || english.trim().isEmpty) {
      throw StateError(
        'Navigation text token ${token.key.name} requires official English '
        'transit text ${name}En',
      );
    }
    final normalizedEnglish = english.trim();
    final normalizedJapanese = japanese.trim();
    if (normalizedEnglish == normalizedJapanese) return normalizedEnglish;
    return '$normalizedEnglish ($normalizedJapanese)';
  }

  String bilingualPlaceArg(String name) {
    final original = stringArg(name);
    if (!isEnglishTransitLocale(locale)) return original;
    final english = token.args['${name}En'];
    if (english == null) return original;
    if (english is! String || english.trim().isEmpty) {
      throw StateError(
        'Navigation text token ${token.key.name} has invalid optional '
        'English text ${name}En',
      );
    }
    final normalizedEnglish = english.trim();
    final normalizedOriginal = original.trim();
    if (normalizedEnglish == normalizedOriginal) return normalizedEnglish;
    return '$normalizedEnglish ($normalizedOriginal)';
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
        officialTransitArg('rideTitle'),
        transitPlaceArg('destination'),
      );
    case NavigationTextKey.preDepartureMain:
      return l10n.navPreDepartureMain;
    case NavigationTextKey.plannedDepartureSub:
      return l10n.navPlannedDepartureSub(stringArg('time'));
    case NavigationTextKey.preStartStatus:
      return l10n.navPreStartStatus;
    case NavigationTextKey.meetingCountdownMain:
      return l10n.navMeetingCountdownMain(intArg('minutes'));
    case NavigationTextKey.meetingScheduledSub:
      return l10n.navMeetingScheduledSub(
        stringArg('time'),
        stringArg('label'),
      );
    case NavigationTextKey.meetingActionMain:
      return l10n.navMeetingActionMain;
    case NavigationTextKey.meetingNextSub:
      return l10n.navMeetingNextSub(
        stringArg('time'),
        stringArg('label'),
      );
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
    case NavigationTextKey.goalArrivedMain:
      return l10n.navGoalArrivedMain(bilingualPlaceArg('destination'));
    case NavigationTextKey.waitingDefaultSub:
      return l10n.navWaitingDefaultSub;
    case NavigationTextKey.waitingStatus:
      return l10n.navWaitingStatus;
    case NavigationTextKey.walkHeadingMain:
      return l10n.navWalkHeadingMain(bilingualPlaceArg('destination'));
    case NavigationTextKey.walkDistanceSub:
      return l10n.navWalkDistanceSub(doubleArg('meters'));
    case NavigationTextKey.positionCheckingMain:
      return l10n.navPositionCheckingMain(officialTransitArg('rideTitle'));
    case NavigationTextKey.busWaitingMain:
      return l10n.navBusWaitingMain;
    case NavigationTextKey.positionCheckingSub:
      return l10n.navPositionCheckingSub;
    case NavigationTextKey.busPositionCheckingAtStopSub:
      return l10n.navBusPositionCheckingAtStopSub(transitPlaceArg('stopName'));
    case NavigationTextKey.waitingToBoardStatus:
      return l10n.navWaitingToBoardStatus;
    case NavigationTextKey.searchingStatus:
      return l10n.navSearchingStatus;
    case NavigationTextKey.approachingBusMain:
      return l10n.navApproachingBusMain(
        officialTransitArg('rideTitle'),
        intArg('count'),
      );
    case NavigationTextKey.approachingRailMain:
      return l10n.navApproachingRailMain(
        officialTransitArg('rideTitle'),
        intArg('count'),
      );
    case NavigationTextKey.nowAtSub:
      return l10n.navNowAtSub(transitPlaceArg('placeName'));
    case NavigationTextKey.arrivedMain:
      return l10n.navArrivedMain;
    case NavigationTextKey.getOffNextMain:
      return l10n.navGetOffNextMain;
    case NavigationTextKey.rideCurrentPlaceMain:
      return l10n.navRideCurrentPlaceMain(
        officialTransitArg('rideTitle'),
        transitPlaceArg('placeName'),
      );
    case NavigationTextKey.transitPlace:
      return transitPlaceArg('placeName');
    case NavigationTextKey.staleBusNotice:
      return '📍';
    case NavigationTextKey.staleRailNotice:
      return '📍';
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
        officialTransitArg('routeTitle'),
      );
    case NavigationTextKey.boardingPlannedSub:
      return l10n.navBoardingPlannedSub(
        stringArg('rideTime'),
        officialTransitArg('routeTitle'),
      );
    case NavigationTextKey.walkToRideCountdownMain:
      return l10n.navWalkToRideCountdownMain(
        stringArg('rideTime'),
        transitPlaceArg('destination'),
        intArg('minutes'),
      );
    case NavigationTextKey.realtimeUnavailableNotice:
      return '📍';
  }
}
