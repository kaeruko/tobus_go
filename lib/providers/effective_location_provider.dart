import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../utils/location_helper.dart';
import 'location_provider.dart';

class EffectiveLocation {
  final String loc;
  final String name;
  EffectiveLocation(this.loc, this.name);
}

/// 本番用のGPS取得と、デバッグ用の位置情報オーバーライドを統合するProvider。
/// HomePageなどのUIはこのProviderを通じて「最終的に使用すべき現在地」を取得する。
final effectiveLocationProvider = FutureProvider<EffectiveLocation>((ref) async {
  final override = ref.watch(locationOverrideProvider);

  if (override != null) {
    final loc = "${override.latitude},${override.longitude}";
    return EffectiveLocation(loc, "現在地(設定)");
  }

  final loc = await LocationHelper.getCurrentLocationString();
  return EffectiveLocation(loc, "現在地");
});
