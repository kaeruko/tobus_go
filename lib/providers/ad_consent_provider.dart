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

ConsentDebugSettings? umpDebugSettings({
  required bool enabled,
  required String geography,
  required String testDeviceId,
}) {
  if (!enabled || (geography.isEmpty && testDeviceId.isEmpty)) return null;
  final region = switch (geography) {
    'eea' => DebugGeography.debugGeographyEea,
    'regulated-us' => DebugGeography.debugGeographyRegulatedUsState,
    'other' => DebugGeography.debugGeographyOther,
    _ => throw StateError('Invalid TOEIGO_TEST_UMP_GEOGRAPHY.'),
  };
  if (testDeviceId.isEmpty || testDeviceId.trim() != testDeviceId) {
    throw StateError(
      'Set TOEIGO_TEST_UMP_DEVICE_ID to the device hash from UMP.',
    );
  }
  return ConsentDebugSettings(
    debugGeography: region,
    testIdentifiers: [testDeviceId],
  );
}

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
    final parameters = ConsentRequestParameters(
      consentDebugSettings: umpDebugSettings(
        enabled:
            kDebugMode &&
            const bool.fromEnvironment('TOEIGO_TEST_ADS') &&
            const bool.fromEnvironment('TOEIGO_TEST_UMP'),
        geography: const String.fromEnvironment('TOEIGO_TEST_UMP_GEOGRAPHY'),
        testDeviceId: const String.fromEnvironment('TOEIGO_TEST_UMP_DEVICE_ID'),
      ),
    );
    final done = Completer<void>();
    ConsentInformation.instance.requestConsentInfoUpdate(
      parameters,
      () => done.complete(),
      (error) => done.completeError(
        StateError('UMP update: ${error.errorCode}: ${error.message}'),
      ),
    );
    await done.future;
  }

  @override
  Future<void> showRequiredForm() async {
    await ConsentForm.loadAndShowConsentFormIfRequired((error) {
      if (error != null) {
        throw StateError('UMP form: ${error.errorCode}: ${error.message}');
      }
    });
  }

  @override
  Future<bool> privacyOptionsRequired() async {
    final status = await ConsentInformation.instance
        .getPrivacyOptionsRequirementStatus();
    return switch (status) {
      PrivacyOptionsRequirementStatus.required => true,
      PrivacyOptionsRequirementStatus.notRequired => false,
      PrivacyOptionsRequirementStatus.unknown => throw StateError(
        'UMP privacy options requirement is unknown.',
      ),
    };
  }

  @override
  Future<bool> canRequestAds() => ConsentInformation.instance.canRequestAds();

  @override
  Future<void> showPrivacyOptions() async {
    await ConsentForm.showPrivacyOptionsForm((error) {
      if (error != null) {
        throw StateError(
          'UMP privacy options: ${error.errorCode}: ${error.message}',
        );
      }
    });
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
