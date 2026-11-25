import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../core/city_profile.dart';
import '../models/fare_models.dart';
import '../models/route_models.dart';
import '../providers/route_search_provider.dart';

class RouteCard extends ConsumerWidget {
  final Candidate candidate;
  final int rank;
  final bool showRank;
  final RouteMeta? meta;
  final FareQuote? fare;
  final Widget? titleTrailing;

  const RouteCard({
    super.key,
    required this.candidate,
    required this.rank,
    this.showRank = true,
    this.meta,
    this.fare,
    this.titleTrailing,
  });

  String _origin(AppLocalizations l10n, Locale locale) {
    final origin = candidate.originName?.trim();
    if (origin != null && origin.isNotEmpty) {
      return localizedOptionalPlaceName(
        locale,
        japanese: origin,
        english: candidate.originNameEn,
        field: 'origin_name_en',
        identity: 'candidate=${candidate.id}',
      );
    }
    if (candidate.steps.isEmpty) return l10n.originFallback;

    return localizedStepEndpointName(
          locale,
          candidate.steps.first,
          origin: true,
        ) ??
        l10n.originFallback;
  }

  String _destination(AppLocalizations l10n, Locale locale) {
    if (meta?.destinationReachable == false) {
      final fallbackName = meta?.fallbackNodeName;
      final stopName = fallbackName == null
          ? l10n.nearestStop
          : localizedOptionalTransitName(
              locale,
              japanese: fallbackName,
              english: meta?.fallbackNodeNameEn,
              field: 'fallback_node_name_en',
              identity: 'candidate=${candidate.id}',
            );
      final walk = meta?.fallbackWalkMinutes;
      final suffix = walk != null ? l10n.destinationWalkSuffix(walk) : '';
      return stopName + suffix;
    }

    final destination = candidate.destinationName?.trim();
    if (destination != null && destination.isNotEmpty) {
      return localizedOptionalPlaceName(
        locale,
        japanese: destination,
        english: candidate.destinationNameEn,
        field: 'destination_name_en',
        identity: 'candidate=${candidate.id}',
      );
    }
    if (candidate.steps.isEmpty) return l10n.destinationFallback;

    return localizedStepEndpointName(
          locale,
          candidate.steps.last,
          origin: false,
        ) ??
        l10n.destinationFallback;
  }

  String? _fareChip(FareQuote? quote, AppLocalizations l10n) {
    if (quote == null) return null;
    if (!quote.isAvailable) return l10n.fareUnavailable;
    final payNow = quote.payNowYen;
    if (payNow == null) return l10n.fareUnknown;
    if (quote.settlementType == 'reimbursement') {
      return l10n.fareReimbursement(payNow);
    }
    if (quote.settlementType == 'free_pass') {
      return l10n.fareFreePass;
    }
    return l10n.farePay(payNow);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final label = CupertinoDynamicColor.resolve(CupertinoColors.label, context);
    final secondaryLabel = CupertinoDynamicColor.resolve(
      CupertinoColors.secondaryLabel,
      context,
    );
    final effectiveFare =
        fare ??
        ref.watch(
          routeSearchProvider.select(
            (state) => state.fareByCandidateId[candidate.id],
          ),
        );
    final fareChip =
        configuredCityKey == 'tokyo' ||
            configuredCityKey == 'sendai' && sendaiReviewedCoordinatesEnabled
        ? null
        : _fareChip(effectiveFare, l10n);
    // Match the route detail's arrival clock. Do not estimate a new
    // arrival from totalTime: this field is already part of the API result.
    final arrivalTime = candidate.arrivalTime?.trim();
    final arrivalChip = arrivalTime == null || arrivalTime.isEmpty
        ? l10n.replanUnknownTime
        : l10n.segmentArrivalAt(arrivalTime);

    return Container(
      decoration: BoxDecoration(
        color: CupertinoDynamicColor.resolve(
          CupertinoColors.systemGrey6,
          context,
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (showRank) ...[
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFF0057B8),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    '$rank',
                    style: const TextStyle(color: CupertinoColors.white),
                  ),
                ),
                const SizedBox(width: 8),
              ],
              Expanded(
                child: Text(
                  localizedCandidateLines(locale, candidate).join(' → '),
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                    color: label,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (titleTrailing != null) ...[
                const SizedBox(width: 6),
                titleTrailing!,
              ],
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              const Icon(
                CupertinoIcons.location_fill,
                size: 14,
                color: CupertinoColors.systemGreen,
              ),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  '${_origin(l10n, locale)} → ${_destination(l10n, locale)}',
                  style: TextStyle(
                    fontSize: 14,
                    color: secondaryLabel,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              _chip(context, arrivalChip),
              _chip(context, l10n.transfersChip(candidate.transfers)),
              _chip(context, l10n.ridesChip(candidate.rides)),
              _chip(
                context,
                candidate.hasUnknownWalkingDistance
                    ? l10n.walkTitle
                    : l10n.walkChip(candidate.walkingDistanceMeters),
              ),
              if (fareChip != null) _chip(context, fareChip),
            ],
          ),
        ],
      ),
    );
  }

  Widget _chip(BuildContext context, String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: CupertinoDynamicColor.resolve(
          CupertinoColors.systemBackground,
          context,
        ),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 12,
          color: CupertinoDynamicColor.resolve(CupertinoColors.label, context),
        ),
      ),
    );
  }
}
