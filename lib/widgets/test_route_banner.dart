import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

/// Local test-only banner. No route, location or user data is supplied.
class TestRouteBanner extends StatefulWidget {
  const TestRouteBanner({super.key, required this.adUnitId});

  final String adUnitId;

  @override
  State<TestRouteBanner> createState() => _TestRouteBannerState();
}

class _TestRouteBannerState extends State<TestRouteBanner> {
  static Future<InitializationStatus>? _initialization;
  BannerAd? _banner;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    try {
      await (_initialization ??= MobileAds.instance.initialize());
      if (!mounted) return;
      final banner = BannerAd(
        adUnitId: widget.adUnitId,
        size: AdSize.banner,
        request: const AdRequest(nonPersonalizedAds: true),
        listener: BannerAdListener(
          onAdLoaded: (ad) {
            if (!mounted || !identical(_banner, ad)) return;
            setState(() => _loaded = true);
          },
          onAdFailedToLoad: (ad, error) {
            if (!identical(_banner, ad)) return;
            debugPrint('TestRouteBanner load failed: ${error.domain} '
                '${error.code}: ${error.message}');
            _banner = null;
            unawaited(ad.dispose());
            if (mounted) setState(() => _loaded = false);
          },
        ),
      );
      _banner = banner;
      await banner.load();
    } catch (error, stack) {
      debugPrint('TestRouteBanner stopped: $error\n$stack');
      final banner = _banner;
      _banner = null;
      if (banner != null) unawaited(banner.dispose());
      if (mounted) setState(() => _loaded = false);
      // Do not retry or switch ad units. Route search is independent of ads.
    }
  }

  @override
  void dispose() {
    final banner = _banner;
    _banner = null;
    if (banner != null) unawaited(banner.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final banner = _banner;
    if (!_loaded || banner == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Center(
        child: SizedBox(
          width: banner.size.width.toDouble(),
          height: banner.size.height.toDouble(),
          child: AdWidget(ad: banner),
        ),
      ),
    );
  }
}
