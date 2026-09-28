import 'package:flutter/material.dart';

import '../logic/trip_navigator.dart';

class ActiveTripAppBarTitle extends StatelessWidget {
  final String appName;
  final String tripTitle;
  final String? contextLabel;
  final Widget? brand;

  const ActiveTripAppBarTitle({
    super.key,
    required this.appName,
    required this.tripTitle,
    this.contextLabel,
    this.brand,
  });

  @override
  Widget build(BuildContext context) {
    final normalizedAppName = appName.trim();
    final normalizedTripTitle = tripTitle.trim();
    final normalizedContextLabel = contextLabel?.trim();

    if (normalizedAppName.isEmpty) {
      throw StateError('移動中ナビのappNameが空です');
    }
    if (normalizedTripTitle.isEmpty) {
      throw StateError('移動中ナビのtripTitleが空です');
    }

    final subtitle = normalizedContextLabel == null ||
            normalizedContextLabel.isEmpty
        ? normalizedTripTitle
        : '$normalizedContextLabel · $normalizedTripTitle';

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        brand ??
            Text(
              normalizedAppName,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: Colors.black,
                fontSize: 16,
                fontWeight: FontWeight.bold,
              ),
            ),
        Text(
          subtitle,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: Colors.black54,
            fontSize: 12,
          ),
        ),
      ],
    );
  }
}


class ActiveTripEndpointCard extends StatelessWidget {
  final String currentLabel;
  final String currentPlace;
  final String destinationLabel;
  final String destinationPlace;

  const ActiveTripEndpointCard({
    super.key,
    required this.currentLabel,
    required this.currentPlace,
    required this.destinationLabel,
    required this.destinationPlace,
  });

  @override
  Widget build(BuildContext context) {
    final normalizedCurrentLabel = currentLabel.trim();
    final normalizedCurrentPlace = currentPlace.trim();
    final normalizedDestinationLabel = destinationLabel.trim();
    final normalizedDestinationPlace = destinationPlace.trim();

    if (normalizedCurrentLabel.isEmpty ||
        normalizedCurrentPlace.isEmpty ||
        normalizedDestinationLabel.isEmpty ||
        normalizedDestinationPlace.isEmpty) {
      throw StateError(
        '移動中の現在地・目的地カードに空の表示値があります: '
        'currentLabel="$currentLabel", currentPlace="$currentPlace", '
        'destinationLabel="$destinationLabel", '
        'destinationPlace="$destinationPlace"',
      );
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(18),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.10),
            blurRadius: 8,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: _EndpointBlock(
              markerColor: const Color(0xFF2D8CFF),
              label: normalizedCurrentLabel,
              place: normalizedCurrentPlace,
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 8),
            child: Icon(
              Icons.arrow_right_alt_rounded,
              color: Color(0xFF8A94A6),
              size: 28,
            ),
          ),
          Expanded(
            child: _EndpointBlock(
              markerColor: const Color(0xFFE94B43),
              label: normalizedDestinationLabel,
              place: normalizedDestinationPlace,
            ),
          ),
        ],
      ),
    );
  }
}

class _EndpointBlock extends StatelessWidget {
  final Color markerColor;
  final String label;
  final String place;

  const _EndpointBlock({
    required this.markerColor,
    required this.label,
    required this.place,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          children: [
            Icon(Icons.location_on, color: markerColor, size: 22),
            const SizedBox(width: 4),
            Expanded(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w800,
                  color: Colors.black87,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 3),
        Text(
          place,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            fontSize: 14,
            height: 1.25,
            fontWeight: FontWeight.w500,
            color: Colors.black87,
          ),
        ),
      ],
    );
  }
}

/// Solo / Group の移動中ナビゲーションで共有する画面骨格。
///
/// この Widget は role や権限を判定しない。Solo / Group member / Group leader
/// 固有の警告・操作・schedule UI は slot として呼び出し側から渡す。
class ActiveTripNavigationView extends StatelessWidget {
  final NavigationState navState;
  final String tripTitle;
  final PreferredSizeWidget appBar;
  final VoidCallback onTapStops;
  final Widget? statusHeaderTrailing;
  final List<Widget> beforeScheduleSections;
  final Widget scheduleSection;
  final List<Widget> afterScheduleSections;
  final Widget? bottomNavigationBar;
  final EdgeInsetsGeometry contentPadding;

  const ActiveTripNavigationView({
    super.key,
    required this.navState,
    required this.tripTitle,
    required this.appBar,
    required this.onTapStops,
    required this.scheduleSection,
    this.statusHeaderTrailing,
    this.beforeScheduleSections = const [],
    this.afterScheduleSections = const [],
    this.bottomNavigationBar,
    this.contentPadding = const EdgeInsets.fromLTRB(16, 12, 16, 24),
  });

  @override
  Widget build(BuildContext context) {
    final normalizedTitle = tripTitle.trim();
    if (normalizedTitle.isEmpty) {
      throw StateError('移動中ナビのtripTitleが空です');
    }

    return Scaffold(
      backgroundColor: navState.color,
      appBar: appBar,
      body: SafeArea(
        child: ListView(
          padding: contentPadding,
          children: [
            if (statusHeaderTrailing != null)
              Align(
                alignment: Alignment.centerRight,
                child: statusHeaderTrailing!,
              ),
            ..._withSpacing(beforeScheduleSections, 10),
            if (statusHeaderTrailing != null ||
                beforeScheduleSections.isNotEmpty)
              const SizedBox(height: 14),
            scheduleSection,
            ..._withSpacing(afterScheduleSections, 14),
          ],
        ),
      ),
      bottomNavigationBar: bottomNavigationBar,
    );
  }

  List<Widget> _withSpacing(List<Widget> sections, double spacing) {
    if (sections.isEmpty) return const [];

    final children = <Widget>[];
    for (final section in sections) {
      children
        ..add(SizedBox(height: spacing))
        ..add(section);
    }
    return children;
  }
}
