import 'package:flutter/material.dart';
import '../l10n/app_localizations.dart';

import '../widgets/group_leader_route_replan_panel.dart';

class GroupLeaderRouteReplanPage extends StatelessWidget {
  final String tripId;

  const GroupLeaderRouteReplanPage({super.key, required this.tripId});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(AppLocalizations.of(context).replanReviewAction),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            AppLocalizations.of(context).groupReplanExplanation,
            style: TextStyle(color: Colors.black54),
          ),
          const SizedBox(height: 12),
          GroupLeaderRouteReplanPanel(tripId: tripId, alwaysShowAction: true),
        ],
      ),
    );
  }
}
