import 'package:flutter/material.dart';

import '../widgets/group_leader_route_replan_panel.dart';

class GroupLeaderRouteReplanPage extends StatelessWidget {
  final String tripId;

  const GroupLeaderRouteReplanPage({
    super.key,
    required this.tripId,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('経路を見直す')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
            '乗車前は保存済みの経路出発地点、移動中は確認できた駅・停留所を基準に、目的地までの経路を現在の時刻で再検索します。',
            style: TextStyle(color: Colors.black54),
          ),
          const SizedBox(height: 12),
          GroupLeaderRouteReplanPanel(
            tripId: tripId,
            alwaysShowAction: true,
          ),
        ],
      ),
    );
  }
}
