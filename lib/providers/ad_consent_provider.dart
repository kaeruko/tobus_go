import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

/// Shared consent gate for explicitly enabled production and UMP debug modes.
/// Fail closed if update, required form or permission checks fail.
final adConsentProvider =
    StateNotifierProvider<AdConsentController, AdConsentState>((ref) {
  final controller = AdConsentController(const GoogleConsentGateway());
  unawaited(Future<void>.microtask(controller.start));
  return controller;
});

class AdConsentState {
  const AdConsentState({
    this.canRequestAds = false,
    this.privacyOptionsRequired = false,
    this.busy = false,
  });

  final bool canRequestAds;
  final bool privacyOptionsRequired;
  final bool busy;
}

abstract interface class ConsentGateway {
  Future<void> update();
  Future<void> showRequiredForm();
  Future<bool> privacyOptionsRequired();
  Future<bool> canRequestAds();
  Future<void> showPrivacyOptions();
}

class GoogleConsentGateway implements ConsentGateway {
  const GoogleConsentGateway();

  @override
  Future<void> update() async {
    final done = Completer<void>();
    ConsentInformation.instance.requestConsentInfoUpdate(
      ConsentRequestParameters(),
      () => done.complete(),
      (error) => done.completeError(
        StateError('UMP update: ${error.errorCode}: ${error.message}'),
      ),
    );
    await done.future;
  }

  @override
  Future<void> showRequiredForm() async {
    final done = Completer<void>();
    ConsentForm.loadAndShowConsentFormIfRequired((error) {
      if (error == null) {
        done.complete();
      } else {
        done.completeError(
          StateError('UMP form: ${error.errorCode}: ${error.message}'),
        );
      }
    });
    await done.future;
  }

  @override
  Future<bool> privacyOptionsRequired() async =>
      await ConsentInformation.instance.getPrivacyOptionsRequirementStatus() ==
      PrivacyOptionsRequirementStatus.required;

  @override
  Future<bool> canRequestAds() => ConsentInformation.instance.canRequestAds();

  @override
  Future<void> showPrivacyOptions() async {
    final done = Completer<void>();
    ConsentForm.showPrivacyOptionsForm((error) {
      if (error == null) {
        done.complete();
      } else {
        done.completeError(
          StateError('UMP privacy options: ${error.errorCode}: ${error.message}'),
        );
      }
    });
    await done.future;
  }
}

class AdConsentController extends StateNotifier<AdConsentState> {
  AdConsentController(this._gateway) : super(const AdConsentState());

  final ConsentGateway _gateway;
  bool _started = false;

  Future<void> start() async {
    if (!mounted || _started) return;
    _started = true;
    state = const AdConsentState(busy: true);
    var required = false;
    try {
      await _gateway.update();
      if (!mounted) return;
      required = await _gateway.privacyOptionsRequired();
      if (!mounted) return;
      await _gateway.showRequiredForm();
      if (!mounted) return;
      required = await _gateway.privacyOptionsRequired();
      if (!mounted) return;
      final allowed = await _gateway.canRequestAds();
      if (mounted) {
        state = AdConsentState(
          canRequestAds: allowed,
          privacyOptionsRequired: required,
        );
      }
    } catch (error, stack) {
      debugPrint('AdConsent stopped: $error\n$stack');
      if (mounted) state = AdConsentState(privacyOptionsRequired: required);
    }
  }

  Future<void> showPrivacyOptions() async {
    if (!mounted || state.busy || !state.privacyOptionsRequired) return;
    // Suppress existing ads while the user is changing their preferences.
    state = const AdConsentState(privacyOptionsRequired: true, busy: true);
    var required = true;
    try {
      await _gateway.showPrivacyOptions();
      if (!mounted) return;
      required = await _gateway.privacyOptionsRequired();
      if (!mounted) return;
      final allowed = await _gateway.canRequestAds();
      if (mounted) {
        state = AdConsentState(
          canRequestAds: allowed,
          privacyOptionsRequired: required,
        );
      }
    } catch (error, stack) {
      debugPrint('AdConsent privacy options stopped: $error\n$stack');
      if (mounted) state = AdConsentState(privacyOptionsRequired: required);
    }
  }
}
