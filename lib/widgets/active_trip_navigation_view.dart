import 'package:flutter/material.dart';

import '../logic/trip_navigator.dart';
import 'trip_navigation_status_card.dart';

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
            TripNavigationStatusCard(
              navState: navState,
              tripTitle: normalizedTitle,
              onTapStops: onTapStops,
              headerTrailing: statusHeaderTrailing,
            ),
            ..._withSpacing(beforeScheduleSections, 10),
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
