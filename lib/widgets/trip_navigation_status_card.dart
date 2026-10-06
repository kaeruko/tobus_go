import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../l10n/navigation_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../logic/trip_navigator.dart';
import '../models/route_models.dart';

/// Shared navigation status card used by both solo and group navigation.
///
/// The changing route state (waiting, approaching, riding, arrival, etc.) is
/// represented entirely by [NavigationState]. Keeping the visual rendering in
/// one widget prevents solo/group screens from drifting when new navigation
/// states are added.
class TripNavigationStatusCard extends StatelessWidget {
  final NavigationState navState;
  final String tripTitle;
  final VoidCallback onTapStops;
  final Widget? headerTrailing;

  const TripNavigationStatusCard({
    super.key,
    required this.navState,
    required this.tripTitle,
    required this.onTapStops,
    this.headerTrailing,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final mainText = localizedNavigationText(
      l10n,
      locale,
      navState.mainTextToken,
      fallback: navState.mainText,
    );
    final subText = localizedNavigationText(
      l10n,
      locale,
      navState.subTextToken,
      fallback: navState.subText,
    );
    final statusLabel = localizedNavigationText(
      l10n,
      locale,
      navState.statusLabelToken,
      fallback: navState.statusLabel,
    );
    final noticeText = navState.noticeText == null
        ? null
        : localizedNavigationText(
            l10n,
            locale,
            navState.noticeTextToken,
            fallback: navState.noticeText!,
          );
    final nextStopName = _localizedNextStopName(locale);
    final showRideRealtimeIndicator =
        noticeText != null &&
        noticeText.isNotEmpty &&
        _usesStructuredRideHeading() &&
        navState.step?.kind == 'bus';
    const compactRealtimeNoticeKeys = <NavigationTextKey>{
      NavigationTextKey.realtimeUnavailableNotice,
      NavigationTextKey.staleBusNotice,
      NavigationTextKey.staleRailNotice,
    };
    final showCompactRealtimeStatus =
        noticeText != null &&
        noticeText.isNotEmpty &&
        compactRealtimeNoticeKeys.contains(navState.noticeTextToken?.key) &&
        !showRideRealtimeIndicator;
    return Card(
      margin: EdgeInsets.zero,
      elevation: 4,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            LayoutBuilder(
              builder: (context, constraints) {
                final statusWidgets = <Widget>[
                  Chip(
                    avatar: const Icon(Icons.location_on, size: 18),
                    label: Text(statusLabel),
                  ),
                  if (showCompactRealtimeStatus)
                    Semantics(
                      key: const ValueKey(
                        'waiting-realtime-status-indicator',
                      ),
                      label: l10n.navRealtimeRefreshingSemantics,
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.sync,
                            size: 17,
                            color: Theme.of(context).colorScheme.primary,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            noticeText,
                            style: const TextStyle(fontSize: 16),
                          ),
                        ],
                      ),
                    ),
                ];

                if (headerTrailing == null) {
                  return Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: statusWidgets,
                  );
                }

                return Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Expanded(
                      child: Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: statusWidgets,
                      ),
                    ),
                    const SizedBox(width: 8),
                    ConstrainedBox(
                      constraints: BoxConstraints(
                        maxWidth: constraints.maxWidth * 0.46,
                      ),
                      child: headerTrailing!,
                    ),
                  ],
                );
              },
            ),
            const SizedBox(height: 18),
            if (_usesStructuredRideHeading())
              _buildStructuredRideHeading(
                context,
                l10n,
                locale,
                showRealtimeIndicator: showRideRealtimeIndicator,
              )
            else if (_usesStructuredApproachingHeading())
              _buildStructuredApproachingHeading(context, l10n, locale)
            else if (_usesStructuredWalkToRideHeading())
              _buildStructuredWalkToRideHeading(context, l10n, locale)
            else if (_usesStructuredDepartureCountdownHeading())
              _buildStructuredDepartureCountdownHeading(
                context,
                l10n,
                locale,
              )
            else if (_usesStructuredGetOffNextHeading())
              _buildStructuredGetOffNextHeading(context, l10n, locale)
            else ...[
              Text(
                mainText,
                style: const TextStyle(
                  fontSize: 42,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                subText,
                style: const TextStyle(
                  fontSize: 21,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
            if (noticeText != null &&
                noticeText.isNotEmpty &&
                !showRideRealtimeIndicator &&
                !showCompactRealtimeStatus) ...[
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.amber.shade100,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.amber.shade700),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.sync, size: 22),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        noticeText,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (navState.remainingStops != null ||
                ((nextStopName?.isNotEmpty ?? false) &&
                    !_usesStructuredWalkToRideHeading())) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (navState.remainingStops != null)
                    ActionChip(
                      avatar: Icon(_remainingIcon(), size: 18),
                      label: Text(_remainingLabel(l10n)),
                      onPressed: onTapStops,
                    ),
                  if ((nextStopName?.isNotEmpty ?? false) &&
                      !_usesStructuredWalkToRideHeading())
                    Chip(label: Text(l10n.nextStop(nextStopName!))),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  bool _usesStructuredRideHeading() {
    return navState.isMoving &&
        navState.step?.isRide == true &&
        navState.remainingStops != null &&
        navState.remainingStops! > 1 &&
        navState.mainTextToken?.key == NavigationTextKey.rideCurrentPlaceMain;
  }

  bool _usesStructuredApproachingHeading() {
    final key = navState.mainTextToken?.key;
    return navState.step?.isRide == true &&
        (key == NavigationTextKey.approachingBusMain ||
            key == NavigationTextKey.approachingRailMain);
  }

  bool _usesStructuredWalkToRideHeading() {
    return navState.mainTextToken?.key ==
        NavigationTextKey.walkToRideCountdownMain;
  }

  bool _usesStructuredGetOffNextHeading() {
    return navState.mainTextToken?.key == NavigationTextKey.getOffNextMain &&
        navState.subTextToken?.key == NavigationTextKey.rideArrivalSummary &&
        navState.step?.isRide == true &&
        navState.remainingStops == 1;
  }

  bool _usesStructuredDepartureCountdownHeading() {
    return navState.mainTextToken?.key ==
            NavigationTextKey.departureCountdownMain &&
        navState.subTextToken?.key == NavigationTextKey.boardingSub;
  }

  Widget _buildStructuredApproachingHeading(
    BuildContext context,
    AppLocalizations l10n,
    Locale locale,
  ) {
    final step = navState.step;
    final token = navState.mainTextToken;
    if (step == null || !step.isRide || token == null) {
      throw StateError('接近中の構造化表示に乗車stepまたはtokenがありません');
    }

    final countValue = token.args['count'];
    if (countValue is! int || countValue <= 0) {
      throw StateError(
        '接近中の構造化表示に正のcountがありません: '
        'stepId=${step.stepId}, count=$countValue',
      );
    }

    final routeTitleJaValue = token.args['rideTitle'];
    if (routeTitleJaValue is! String || routeTitleJaValue.trim().isEmpty) {
      throw StateError(
        '接近中の構造化表示にrideTitleがありません: stepId=${step.stepId}',
      );
    }
    final routeTitleJa = routeTitleJaValue.trim();
    final routeTitle = isEnglishTransitLocale(locale)
        ? (() {
            final english = token.args['rideTitleEn'];
            if (english is! String || english.trim().isEmpty) {
              throw StateError(
                '接近中の構造化表示に公式英語rideTitleEnがありません: '
                'stepId=${step.stepId}',
              );
            }
            return english.trim();
          })()
        : normalizeJapaneseTransitDisplayText(routeTitleJa);

    late final String distanceText;
    late final IconData icon;
    switch (step.kind) {
      case 'bus':
        if (token.key != NavigationTextKey.approachingBusMain) {
          throw StateError(
            'バス接近中表示にapproachingBusMain tokenがありません: '
            'stepId=${step.stepId}, token=${token.key.name}',
          );
        }
        distanceText = l10n.navApproachingBusDistance(countValue);
        icon = Icons.directions_bus;
      case 'rail':
        if (token.key != NavigationTextKey.approachingRailMain) {
          throw StateError(
            '鉄道接近中表示にapproachingRailMain tokenがありません: '
            'stepId=${step.stepId}, token=${token.key.name}',
          );
        }
        distanceText = l10n.navApproachingRailDistance(countValue);
        icon = Icons.train;
      default:
        throw StateError(
          '接近中の構造化表示で未対応のstep kindです: ${step.kind}',
        );
    }

    final boardingText = localizedNavigationText(
      l10n,
      locale,
      navState.subTextToken,
      fallback: navState.subText,
    ).trim();
    if (boardingText.isEmpty) {
      throw StateError(
        '接近中の構造化表示に乗車地点表示がありません: stepId=${step.stepId}',
      );
    }

    return Column(
      key: const ValueKey('approaching-ride-heading'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Icon(icon, size: 20),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                routeTitle,
                key: const ValueKey('approaching-route-title'),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        Text(
          distanceText,
          key: const ValueKey('approaching-distance'),
          maxLines: 2,
          overflow: TextOverflow.visible,
          style: const TextStyle(
            fontSize: 34,
            height: 1.08,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          boardingText,
          key: const ValueKey('approaching-boarding-place'),
          maxLines: 2,
          overflow: TextOverflow.visible,
          style: const TextStyle(
            fontSize: 21,
            height: 1.2,
            fontWeight: FontWeight.bold,
          ),
        ),
      ],
    );
  }

  Widget _buildStructuredDepartureCountdownHeading(
    BuildContext context,
    AppLocalizations l10n,
    Locale locale,
  ) {
    final mainToken = navState.mainTextToken;
    if (mainToken == null ||
        mainToken.key != NavigationTextKey.departureCountdownMain) {
      throw StateError('出発待機の構造化表示にdeparture countdown tokenがありません');
    }

    String requiredString(
      NavigationTextToken token,
      String name, {
      required String role,
    }) {
      final value = token.args[name];
      if (value is! String || value.trim().isEmpty) {
        throw StateError('出発待機の構造化表示に$role.$nameがありません');
      }
      return value.trim();
    }

    final leaveTime = requiredString(
      mainToken,
      'leaveTime',
      role: 'main',
    );
    final minutesValue = mainToken.args['minutes'];
    if (minutesValue is! int) {
      throw StateError('出発待機の構造化表示にmain.minutesがありません');
    }

    final boardingToken = navState.subTextToken;
    if (boardingToken == null ||
        boardingToken.key != NavigationTextKey.boardingSub) {
      throw StateError('出発待機の構造化表示にboarding tokenがありません');
    }
    final rideTime = requiredString(
      boardingToken,
      'rideTime',
      role: 'boarding',
    );
    final routeTitleJa = requiredString(
      boardingToken,
      'routeTitle',
      role: 'boarding',
    );
    final routeTitleEnValue = boardingToken.args['routeTitleEn'];
    if (isEnglishTransitLocale(locale) &&
        (routeTitleEnValue is! String || routeTitleEnValue.trim().isEmpty)) {
      throw StateError('出発待機の構造化表示にboarding.routeTitleEnがありません');
    }
    final routeTitleEn = routeTitleEnValue is String
        ? routeTitleEnValue.trim()
        : null;
    final primaryRouteTitle =
        isEnglishTransitLocale(locale) && routeTitleEn != null
        ? routeTitleEn
        : routeTitleJa;
    final secondaryRouteTitle =
        isEnglishTransitLocale(locale) &&
            routeTitleEn != null &&
            routeTitleEn != routeTitleJa
        ? routeTitleJa
        : null;

    final colors = Theme.of(context).colorScheme;
    return Column(
      key: const ValueKey('departure-countdown-heading'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.schedule, size: 30, color: colors.primary),
            const SizedBox(width: 10),
            Text(
              leaveTime,
              style: const TextStyle(
                fontSize: 46,
                height: 1,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(width: 10),
            Text(
              l10n.navDepartureLabel,
              key: const ValueKey('departure-countdown-label'),
              style: TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w600,
                color: colors.onSurfaceVariant,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.only(left: 40),
          child: Text(
            l10n.navDepartureRemaining(minutesValue),
            style: const TextStyle(
              fontSize: 28,
              height: 1.05,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        const SizedBox(height: 18),
        Semantics(
          button: true,
          label: l10n.segmentGuideTitle,
          child: Material(
            color: colors.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(12),
            child: InkWell(
              key: const ValueKey('departure-boarding-route-action'),
              borderRadius: BorderRadius.circular(12),
              onTap: onTapStops,
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 11,
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.directions_transit,
                      size: 21,
                      color: colors.primary,
                    ),
                    const SizedBox(width: 9),
                    Text(
                      rideTime,
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            primaryRouteTitle,
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 17,
                              height: 1.2,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          if (secondaryRouteTitle != null) ...[
                            const SizedBox(height: 2),
                            Text(
                              secondaryRouteTitle,
                              style: TextStyle(
                                fontSize: 13,
                                color: colors.onSurfaceVariant,
                              ),
                            ),
                          ],
                          const SizedBox(height: 4),
                          Text(
                            l10n.boarding,
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w700,
                              color: colors.primary,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildStructuredWalkToRideHeading(
    BuildContext context,
    AppLocalizations l10n,
    Locale locale,
  ) {
    final mainToken = navState.mainTextToken;
    if (mainToken == null ||
        mainToken.key != NavigationTextKey.walkToRideCountdownMain) {
      throw StateError('徒歩→乗車の構造化表示にmain tokenがありません');
    }

    String requiredString(
      NavigationTextToken token,
      String name, {
      required String role,
    }) {
      final value = token.args[name];
      if (value is! String || value.trim().isEmpty) {
        throw StateError('徒歩→乗車の構造化表示に$role.$nameがありません');
      }
      return value.trim();
    }

    final minutesValue = mainToken.args['minutes'];
    if (minutesValue is! int) {
      throw StateError('徒歩→乗車の構造化表示にmain.minutesがありません');
    }
    final destinationJa = requiredString(
      mainToken,
      'destination',
      role: 'main',
    );
    final destinationEnValue = mainToken.args['destinationEn'];
    if (destinationEnValue != null &&
        (destinationEnValue is! String || destinationEnValue.trim().isEmpty)) {
      throw StateError('徒歩→乗車のdestinationEnが不正です');
    }
    final destinationEn = destinationEnValue is String
        ? destinationEnValue.trim()
        : null;

    final primaryDestination =
        isEnglishTransitLocale(locale) && destinationEn != null
        ? destinationEn
        : destinationJa;
    final secondaryDestination =
        isEnglishTransitLocale(locale) &&
            destinationEn != null &&
            destinationEn != destinationJa
        ? destinationJa
        : null;

    final boardingToken = navState.subTextToken;
    if (boardingToken == null ||
        (boardingToken.key != NavigationTextKey.boardingSub &&
            boardingToken.key != NavigationTextKey.boardingPlannedSub)) {
      throw StateError('徒歩→乗車の構造化表示にboarding tokenがありません');
    }
    final rideTime = requiredString(
      boardingToken,
      'rideTime',
      role: 'boarding',
    );
    final routeTitleJa = requiredString(
      boardingToken,
      'routeTitle',
      role: 'boarding',
    );
    final routeTitleEnValue = boardingToken.args['routeTitleEn'];
    if (isEnglishTransitLocale(locale) &&
        (routeTitleEnValue is! String || routeTitleEnValue.trim().isEmpty)) {
      throw StateError('徒歩→乗車の構造化表示にboarding.routeTitleEnがありません');
    }
    final routeTitleEn = routeTitleEnValue is String
        ? routeTitleEnValue.trim()
        : null;
    final primaryRouteTitle =
        isEnglishTransitLocale(locale) && routeTitleEn != null
        ? routeTitleEn
        : routeTitleJa;
    final secondaryRouteTitle =
        isEnglishTransitLocale(locale) &&
            routeTitleEn != null &&
            routeTitleEn != routeTitleJa
        ? routeTitleJa
        : null;
    final countdown = l10n.navWalkBoardingCountdown(minutesValue);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.directions_walk, size: 20),
            const SizedBox(width: 7),
            Text(
              l10n.categoryWalk.toUpperCase(),
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w800,
                letterSpacing: 0.8,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                countdown,
                textAlign: TextAlign.right,
                softWrap: true,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Text(
          primaryDestination,
          maxLines: 2,
          overflow: TextOverflow.visible,
          style: const TextStyle(
            fontSize: 34,
            height: 1.08,
            fontWeight: FontWeight.w800,
          ),
        ),
        if (secondaryDestination != null) ...[
          const SizedBox(height: 3),
          Text(
            secondaryDestination,
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w600,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
        const SizedBox(height: 16),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.directions_bus, size: 20),
              const SizedBox(width: 9),
              Text(
                rideTime,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      primaryRouteTitle,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    if (secondaryRouteTitle != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        secondaryRouteTitle,
                        style: TextStyle(
                          fontSize: 13,
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildStructuredGetOffNextHeading(
    BuildContext context,
    AppLocalizations l10n,
    Locale locale,
  ) {
    final step = navState.step;
    final token = navState.subTextToken;
    if (step == null || !step.isRide || token == null) {
      throw StateError('次で降りますの構造化表示に乗車stepまたはtokenがありません');
    }
    if (token.key != NavigationTextKey.rideArrivalSummary) {
      throw StateError(
        '次で降りますの構造化表示にrideArrivalSummary tokenがありません: '
        'token=${token.key.name}',
      );
    }

    String requiredString(String name) {
      final value = token.args[name];
      if (value is! String || value.trim().isEmpty) {
        throw StateError(
          '次で降りますの構造化表示に$nameがありません: stepId=${step.stepId}',
        );
      }
      return value.trim();
    }

    final arrivalTime = requiredString('arrivalTime');
    final routeTitleJa = requiredString('rideTitle');
    final destinationJa = requiredString('destination');

    final routeTitleEnValue = token.args['rideTitleEn'];
    final destinationEnValue = token.args['destinationEn'];
    if (isEnglishTransitLocale(locale)) {
      if (routeTitleEnValue is! String || routeTitleEnValue.trim().isEmpty) {
        throw StateError(
          '次で降りますの構造化表示にrideTitleEnがありません: '
          'stepId=${step.stepId}',
        );
      }
      if (destinationEnValue is! String ||
          destinationEnValue.trim().isEmpty) {
        throw StateError(
          '次で降りますの構造化表示にdestinationEnがありません: '
          'stepId=${step.stepId}',
        );
      }
    }

    final routeTitle = isEnglishTransitLocale(locale)
        ? localizedTransitName(
            locale,
            japanese: routeTitleJa,
            english: (routeTitleEnValue as String).trim(),
            field: 'rideTitleEn',
            identity: 'stepId=${step.stepId}',
          )
        : routeTitleJa;
    final destination = isEnglishTransitLocale(locale)
        ? localizedTransitName(
            locale,
            japanese: destinationJa,
            english: (destinationEnValue as String).trim(),
            field: 'destinationEn',
            identity: 'stepId=${step.stepId}',
          )
        : destinationJa;

    const detailStyle = TextStyle(
      fontSize: 21,
      height: 1.2,
      fontWeight: FontWeight.bold,
    );

    return Column(
      key: const ValueKey('get-off-next-heading'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l10n.navGetOffNextMain,
          style: const TextStyle(
            fontSize: 42,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          arrivalTime,
          key: const ValueKey('get-off-next-arrival-time'),
          style: detailStyle,
        ),
        const SizedBox(height: 2),
        Text(
          routeTitle,
          key: const ValueKey('get-off-next-route-title'),
          maxLines: 2,
          overflow: TextOverflow.visible,
          style: detailStyle,
        ),
        const SizedBox(height: 2),
        Text(
          l10n.navArrivalPlannedDestination(destination),
          key: const ValueKey('get-off-next-destination'),
          maxLines: 2,
          overflow: TextOverflow.visible,
          style: detailStyle,
        ),
      ],
    );
  }

  Widget _buildStructuredRideHeading(
    BuildContext context,
    AppLocalizations l10n,
    Locale locale, {
    bool showRealtimeIndicator = false,
  }) {
    final step = navState.step;
    final token = navState.mainTextToken;
    if (step == null || !step.isRide || token == null) {
      throw StateError('構造化乗車表示に乗車stepまたはtokenがありません');
    }

    final routeTitle = _localizedRouteTitle(locale, step);
    final place = _localizedCurrentPlace(locale, token);
    final direction = _localizedRideDirection(l10n, locale, step);
    final arrivalSummary = _compactArrivalSummary(l10n, locale, step);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Icon(
              step.kind == 'rail' ? Icons.train : Icons.directions_bus,
              size: 20,
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Row(
                children: [
                  Flexible(
                    child: Text(
                      routeTitle,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  if (showRealtimeIndicator) ...[
                    const SizedBox(width: 6),
                    Semantics(
                      key: const ValueKey('ride-realtime-status-indicator'),
                      label: l10n.navRealtimeRefreshingSemantics,
                      child: Icon(
                        Icons.sync,
                        size: 16,
                        color: Theme.of(context).colorScheme.primary,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
        if (direction != null) ...[
          const SizedBox(height: 3),
          Padding(
            padding: const EdgeInsets.only(left: 27),
            child: Text(
              direction,
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
        ],
        const SizedBox(height: 14),
        Text(
          place.primary,
          maxLines: 2,
          overflow: TextOverflow.visible,
          style: const TextStyle(
            fontSize: 30,
            height: 1.12,
            fontWeight: FontWeight.w800,
          ),
        ),
        if (place.secondary != null) ...[
          const SizedBox(height: 2),
          Text(
            place.secondary!,
            style: const TextStyle(
              fontSize: 20,
              height: 1.15,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
        const SizedBox(height: 10),
        Text(
          arrivalSummary,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            fontSize: 16,
            height: 1.25,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }

  String _localizedRouteTitle(Locale locale, StepSeg step) {
    final japanese = step.title.trim();
    if (japanese.isEmpty) {
      throw StateError('構造化乗車表示に路線名がありません: stepId=${step.stepId}');
    }
    if (!isEnglishTransitLocale(locale)) return japanese;

    final english = step.titleEn?.trim();
    if (english == null || english.isEmpty) {
      throw StateError('構造化乗車表示に公式英語路線名がありません: stepId=${step.stepId}');
    }
    return english;
  }

  _RidePlaceParts _localizedCurrentPlace(
    Locale locale,
    NavigationTextToken token,
  ) {
    final japanese = token.args['placeName'];
    if (japanese is! String || japanese.trim().isEmpty) {
      throw StateError('構造化乗車表示に現在地がありません: token=${token.key.name}');
    }
    final normalizedJapanese = japanese.trim();
    if (!isEnglishTransitLocale(locale)) {
      return _RidePlaceParts(primary: normalizedJapanese);
    }

    final english = token.args['placeNameEn'];
    if (english is! String || english.trim().isEmpty) {
      throw StateError('構造化乗車表示に公式英語現在地がありません: token=${token.key.name}');
    }
    final normalizedEnglish = english.trim();
    return _RidePlaceParts(
      primary: normalizedEnglish,
      secondary: normalizedEnglish == normalizedJapanese
          ? null
          : '($normalizedJapanese)',
    );
  }

  String? _localizedRideDirection(
    AppLocalizations l10n,
    Locale locale,
    StepSeg step,
  ) {
    if (step.kind != 'rail') return null;
    final progress = navState.railProgress;
    if (progress == null) {
      throw StateError('構造化鉄道乗車表示にRailProgressがありません: stepId=${step.stepId}');
    }

    if (isEnglishTransitLocale(locale)) {
      final english = progress.tripHeadsignEn?.trim();
      if (english == null || english.isEmpty) {
        throw StateError('構造化鉄道乗車表示に公式英語行先がありません: stepId=${step.stepId}');
      }
      return l10n.navRideDirection(english);
    }

    var japanese = progress.tripHeadsign.trim();
    if (japanese.isEmpty) {
      throw StateError('構造化鉄道乗車表示に行先がありません: stepId=${step.stepId}');
    }
    if (japanese.endsWith('行')) {
      japanese = japanese.substring(0, japanese.length - 1);
    }
    return l10n.navRideDirection(japanese);
  }

  String _compactArrivalSummary(
    AppLocalizations l10n,
    Locale locale,
    StepSeg step,
  ) {
    final arrivalTime = step.arrivalTime?.trim();
    if (arrivalTime == null || arrivalTime.isEmpty) {
      throw StateError('構造化乗車表示に到着予定時刻がありません: stepId=${step.stepId}');
    }
    final destination = step.toName?.trim();
    if (destination == null || destination.isEmpty) {
      throw StateError('構造化乗車表示に降車地点がありません: stepId=${step.stepId}');
    }
    final localizedDestination = isEnglishTransitLocale(locale)
        ? localizedTransitName(
            locale,
            japanese: destination,
            english: step.toNameEn,
            field: 'to_en',
            identity: 'stepId=${step.stepId}',
          )
        : destination;
    return l10n.navCompactRideArrival(arrivalTime, localizedDestination);
  }

  String? _localizedNextStopName(Locale locale) {
    final japanese = navState.nextStopName?.trim();
    if (japanese == null || japanese.isEmpty) return null;

    if (navState.step?.isRide == true) {
      return localizedOptionalTransitName(
        locale,
        japanese: japanese,
        english: navState.nextStopNameEn,
        field: 'nextStopNameEn',
        identity: 'stepId=${navState.step!.stepId}',
      );
    }

    return localizedOptionalPlaceName(
      locale,
      japanese: japanese,
      english: navState.nextStopNameEn,
      field: 'nextStopNameEn',
      identity: 'stepId=${navState.step?.stepId ?? '<unknown>'}',
    );
  }

  String _remainingLabel(AppLocalizations l10n) {
    final remaining = navState.remainingStops;
    if (remaining == null) {
      throw StateError('remainingStops がない状態で残り表示を構築しました');
    }

    switch (navState.step?.kind) {
      case 'bus':
        return l10n.remainingBusStops(remaining);
      case 'rail':
        return l10n.remainingRailStops(remaining);
      default:
        throw StateError('残り停車数表示の未対応step kindです: ${navState.step?.kind}');
    }
  }

  IconData _remainingIcon() {
    switch (navState.step?.kind) {
      case 'bus':
        return Icons.directions_bus;
      case 'rail':
        return Icons.train;
      default:
        throw StateError('残り停車数アイコンの未対応step kindです: ${navState.step?.kind}');
    }
  }
}

class _RidePlaceParts {
  final String primary;
  final String? secondary;

  const _RidePlaceParts({required this.primary, this.secondary});
}

/// Compact navigation details rendered inside the active schedule row.
///
/// Unlike [TripNavigationStatusCard], this widget does not repeat the trip title
/// or render a large status heading. It keeps only the actionable navigation
/// details next to the step the user is currently following.
class TripNavigationInlineStatus extends StatelessWidget {
  final NavigationState navState;
  final VoidCallback onTapStops;

  const TripNavigationInlineStatus({
    super.key,
    required this.navState,
    required this.onTapStops,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final mainText = localizedNavigationText(
      l10n,
      locale,
      navState.mainTextToken,
      fallback: navState.mainText,
    ).trim();
    final subText = localizedNavigationText(
      l10n,
      locale,
      navState.subTextToken,
      fallback: navState.subText,
    ).trim();
    final noticeText = navState.noticeText == null
        ? null
        : localizedNavigationText(
            l10n,
            locale,
            navState.noticeTextToken,
            fallback: navState.noticeText!,
          ).trim();
    final nextStopName = _localizedInlineNextStopName(locale);

    final hideGenericWaitingHeading =
        navState.mainTextToken?.key == NavigationTextKey.busWaitingMain;
    final showMain =
        mainText.isNotEmpty &&
        !hideGenericWaitingHeading &&
        mainText != subText;
    final showSub = subText.isNotEmpty;

    return Column(
      key: const ValueKey('trip-navigation-inline-status'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (showMain)
          Text(
            mainText,
            style: const TextStyle(
              fontSize: 14,
              height: 1.25,
              fontWeight: FontWeight.w700,
            ),
          ),
        if (showMain && showSub) const SizedBox(height: 3),
        if (showSub)
          Text(
            subText,
            style: TextStyle(
              fontSize: 13,
              height: 1.3,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        if (noticeText != null && noticeText.isNotEmpty) ...[
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            decoration: BoxDecoration(
              color: Colors.amber.shade100,
              borderRadius: BorderRadius.circular(9),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.sync, size: 17),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    noticeText,
                    style: const TextStyle(
                      fontSize: 12,
                      height: 1.3,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
        if (navState.remainingStops != null ||
            (nextStopName?.isNotEmpty ?? false)) ...[
          const SizedBox(height: 8),
          Wrap(
            spacing: 12,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if ((nextStopName?.isNotEmpty ?? false))
                Text(
                  l10n.nextStop(nextStopName!),
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              if (navState.remainingStops != null)
                InkWell(
                  borderRadius: BorderRadius.circular(6),
                  onTap: onTapStops,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 2,
                      vertical: 2,
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(_inlineRemainingIcon(), size: 15),
                        const SizedBox(width: 4),
                        Text(
                          _inlineRemainingLabel(l10n),
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ],
      ],
    );
  }

  String? _localizedInlineNextStopName(Locale locale) {
    final japanese = navState.nextStopName?.trim();
    if (japanese == null || japanese.isEmpty) return null;

    if (navState.step?.isRide == true) {
      return localizedOptionalTransitName(
        locale,
        japanese: japanese,
        english: navState.nextStopNameEn,
        field: 'nextStopNameEn',
        identity: 'stepId=${navState.step!.stepId}',
      );
    }

    return localizedOptionalPlaceName(
      locale,
      japanese: japanese,
      english: navState.nextStopNameEn,
      field: 'nextStopNameEn',
      identity: 'stepId=${navState.step?.stepId ?? '<unknown>'}',
    );
  }

  String _inlineRemainingLabel(AppLocalizations l10n) {
    final remaining = navState.remainingStops;
    if (remaining == null) {
      throw StateError('remainingStops がない状態でインライン残り表示を構築しました');
    }

    return switch (navState.step?.kind) {
      'bus' => l10n.remainingBusStops(remaining),
      'rail' => l10n.remainingRailStops(remaining),
      _ => throw StateError(
        'インライン残り停車数表示の未対応step kindです: '
        '${navState.step?.kind}',
      ),
    };
  }

  IconData _inlineRemainingIcon() {
    return switch (navState.step?.kind) {
      'bus' => Icons.directions_bus,
      'rail' => Icons.train,
      _ => throw StateError(
        'インライン残り停車数アイコンの未対応step kindです: '
        '${navState.step?.kind}',
      ),
    };
  }
}
