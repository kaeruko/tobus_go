import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/member_mode_provider.dart';
import '../services/bus_location_source.dart';

/// Solo / Group の移動中ナビで共通利用する Realtime 操作。
///
/// FakeBus のデバッグ操作もここへ集約し、画面ごとに
/// `FakeBusLocationSource` の型判定や `pollNow()` 呼び出しを複製しない。
class ActiveTripRealtimeActions extends ConsumerWidget {
  const ActiveTripRealtimeActions({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final busSource = ref.read(busLocationSourceProvider);

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (busSource is FakeBusLocationSource)
          IconButton(
            tooltip: 'Fakeバスを次の停留所へ',
            icon: const Icon(Icons.skip_next),
            onPressed: () async {
              busSource.advance();
              await ref.read(memberModeControllerProvider.notifier).pollNow();
            },
          ),
        IconButton(
          tooltip: '現在地を更新',
          icon: const Icon(Icons.refresh),
          onPressed: () =>
              ref.read(memberModeControllerProvider.notifier).pollNow(),
        ),
      ],
    );
  }
}
