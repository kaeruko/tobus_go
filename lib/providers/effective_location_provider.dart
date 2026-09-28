import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../utils/location_helper.dart';
import 'location_provider.dart';

class EffectiveLocation {
  final String loc;
  final String nameJa;
  final String nameEn;

  const EffectiveLocation({
    required this.loc,
    required this.nameJa,
    required this.nameEn,
  });
}

/// 本番用のGPS取得と、デバッグ用の位置情報オーバーライドを統合するProvider。
/// HomePageなどのUIはこのProviderを通じて「最終的に使用すべき現在地」を取得する。
final effectiveLocationProvider = FutureProvider<EffectiveLocation>((ref) async {
  final override = ref.watch(locationOverrideProvider);

  if (override != null) {
    return EffectiveLocation(
      loc: '${override.latitude},${override.longitude}',
      nameJa: '現在地(設定)',
      nameEn: 'Current location (set)',
    );
  }

  final loc = await LocationHelper.getCurrentLocationString();
  return EffectiveLocation(
    loc: loc,
    nameJa: '現在地',
    nameEn: 'Current location',
  );
});
