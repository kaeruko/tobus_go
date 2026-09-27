import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart'
    show
        FlutterError,
        FlutterErrorDetails,
        TargetPlatform,
        defaultTargetPlatform,
        kReleaseMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'api_endpoint_source.dart';
import 'constants.dart';
import 'core/city_profile.dart';
import 'firebase_options.dart';
import 'l10n/app_localizations.dart';
import 'pages/force_update_page.dart';
import 'pages/member_mode_page.dart';
import 'pages/root_tabs.dart';
import 'providers/app_session_provider.dart';
import 'providers/city_profile_provider.dart';
import 'runtime_config_source.dart';

class RootGate extends ConsumerStatefulWidget {
  const RootGate({super.key});

  @override
  ConsumerState<RootGate> createState() => _RootGateState();
}

class _RootGateState extends ConsumerState<RootGate> {
  static const Duration _bootstrapTimeout = Duration(seconds: 20);

  late Future<_BootstrapResult> _bootstrapFuture;

  @override
  void initState() {
    super.initState();
    _bootstrapFuture = _bootstrap();
  }

  Future<_BootstrapResult> _bootstrap() async {
    try {
      final cityProfile = ref.read(cityProfileProvider);
      final explicitApiBase = kApiBaseOverride.trim();
      final runtimeConfigFileId = runtimeConfigGoogleDriveFileIdForCity(
        cityProfile.city,
      );
      final legacyApiFileId = apiGoogleDriveFileIdForCity(cityProfile.city);

      RuntimeConfig? runtimeConfig;
      AppVersion? currentVersion;

      if (!kReleaseMode && explicitApiBase.isNotEmpty) {
        configureApiBase(parseExplicitApiBaseOverride(explicitApiBase));
      } else if (runtimeConfigFileId != null) {
        runtimeConfig = await loadRuntimeConfigFromGoogleDrive(
          googleDriveFileId: runtimeConfigFileId,
        ).timeout(_bootstrapTimeout);
        configureApiBase(runtimeConfig.apiBase);

        final packageInfo = await PackageInfo.fromPlatform().timeout(
          _bootstrapTimeout,
        );
        currentVersion = AppVersion.parse(
          packageInfo.version,
          fieldName: 'installed app version',
        );
        if (runtimeConfig.requiresUpdate(currentVersion)) {
          return _BootstrapResult(
            runtimeConfig: runtimeConfig,
            currentVersion: currentVersion,
          );
        }
      } else if (legacyApiFileId != null) {
        final apiBaseUri = await loadApiBaseUriFromGoogleDrive(
          googleDriveFileId: legacyApiFileId,
        ).timeout(_bootstrapTimeout);
        configureApiBase(apiBaseUri);
      } else if (explicitApiBase.isNotEmpty) {
        configureApiBase(parseExplicitApiBaseOverride(explicitApiBase));
      } else {
        throw StateError(
          'No runtime API endpoint source is configured for ${cityProfile.key}. '
          'Provide API_BASE explicitly until this city has a Google Drive '
          'endpoint or runtime config file configured.',
        );
      }

      if (!cityProfile.distribution.firebaseEnabled) {
        return _BootstrapResult(
          runtimeConfig: runtimeConfig,
          currentVersion: currentVersion,
        );
      }
      if (cityProfile.city != AppCity.tokyo) {
        throw StateError(
          'Firebase is enabled for ${cityProfile.key}, but no city-specific '
          'Firebase configuration is registered.',
        );
      }

      try {
        if (Firebase.apps.isEmpty) {
          await Firebase.initializeApp(
            options: DefaultFirebaseOptions.currentPlatform,
          ).timeout(_bootstrapTimeout);
        }
      } on FirebaseException catch (error) {
        if (error.code != 'duplicate-app') {
          rethrow;
        }
      }

      await ref.read(appSessionProvider.notifier).initialize();
      return _BootstrapResult(
        runtimeConfig: runtimeConfig,
        currentVersion: currentVersion,
      );
    } catch (error, stackTrace) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          library: 'application bootstrap',
        ),
      );
      rethrow;
    }
  }

  void _retry() {
    setState(() {
      _bootstrapFuture = _bootstrap();
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);

    return FutureBuilder<_BootstrapResult>(
      future: _bootstrapFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const CupertinoPageScaffold(
            child: Center(child: CupertinoActivityIndicator()),
          );
        }

        if (snapshot.hasError) {
          return CupertinoPageScaffold(
            child: SafeArea(
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        l10n.bootstrapFailed,
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        snapshot.error.toString(),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 20),
                      CupertinoButton.filled(
                        onPressed: _retry,
                        child: Text(l10n.retry),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          );
        }

        final cityProfile = ref.watch(cityProfileProvider);
        final bootstrapResult = snapshot.data;
        if (bootstrapResult == null) {
          throw StateError('Bootstrap completed without a result.');
        }
        if (bootstrapResult.requiresUpdate) {
          final runtimeConfig = bootstrapResult.runtimeConfig;
          final currentVersion = bootstrapResult.currentVersion;
          if (runtimeConfig == null || currentVersion == null) {
            throw StateError(
              'Force-update state is missing runtime config or current version.',
            );
          }
          return ForceUpdatePage(
            messageJa: runtimeConfig.updateMessageJa,
            messageEn: runtimeConfig.updateMessageEn,
            currentVersion: currentVersion.toString(),
            minimumVersion: runtimeConfig.minimumSupportedVersion.toString(),
            storeUri: _updateStoreUri(runtimeConfig, cityProfile),
          );
        }

        if (!cityProfile.capabilities.features.groupTrips) {
          return const RootTabs();
        }

        final appSession = ref.watch(appSessionProvider);
        if (appSession.isMemberMode) {
          return const MemberModePage();
        }

        return const RootTabs();
      },
    );
  }
}


Uri? _updateStoreUri(RuntimeConfig config, CityProfile cityProfile) {
  switch (defaultTargetPlatform) {
    case TargetPlatform.android:
      return config.androidStoreUrl ??
          Uri.https(
            'play.google.com',
            '/store/apps/details',
            {'id': cityProfile.distribution.androidApplicationId},
          );
    case TargetPlatform.iOS:
      return config.iosStoreUrl;
    case TargetPlatform.fuchsia:
    case TargetPlatform.linux:
    case TargetPlatform.macOS:
    case TargetPlatform.windows:
      return null;
  }
}

class _BootstrapResult {
  final RuntimeConfig? runtimeConfig;
  final AppVersion? currentVersion;

  const _BootstrapResult({
    required this.runtimeConfig,
    required this.currentVersion,
  });

  bool get requiresUpdate {
    final config = runtimeConfig;
    final version = currentVersion;
    return config != null && version != null && config.requiresUpdate(version);
  }
}
