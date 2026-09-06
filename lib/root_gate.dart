import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart'
    show FlutterError, FlutterErrorDetails, kReleaseMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_endpoint_source.dart';
import 'constants.dart';
import 'core/city_profile.dart';
import 'firebase_options.dart';
import 'pages/member_mode_page.dart';
import 'pages/root_tabs.dart';
import 'providers/app_session_provider.dart';
import 'providers/city_profile_provider.dart';

class RootGate extends ConsumerStatefulWidget {
  const RootGate({super.key});

  @override
  ConsumerState<RootGate> createState() => _RootGateState();
}

class _RootGateState extends ConsumerState<RootGate> {
  static const Duration _bootstrapTimeout = Duration(seconds: 20);

  late Future<void> _bootstrapFuture;

  @override
  void initState() {
    super.initState();
    _bootstrapFuture = _bootstrap();
  }

  Future<void> _bootstrap() async {
    try {
      final cityProfile = ref.read(cityProfileProvider);
      final explicitApiBase = kApiBaseOverride.trim();
      final googleDriveFileId = apiGoogleDriveFileIdForCity(cityProfile.city);

      if (googleDriveFileId != null) {
        if (!kReleaseMode && explicitApiBase.isNotEmpty) {
          configureApiBase(parseExplicitApiBaseOverride(explicitApiBase));
        } else {
          final apiBaseUri = await loadApiBaseUriFromGoogleDrive(
            googleDriveFileId: googleDriveFileId,
          ).timeout(_bootstrapTimeout);
          configureApiBase(apiBaseUri);
        }
      } else if (explicitApiBase.isNotEmpty) {
        configureApiBase(parseExplicitApiBaseOverride(explicitApiBase));
      } else {
        throw StateError(
          'No runtime API endpoint source is configured for ${cityProfile.key}. '
          'Provide API_BASE explicitly until this city has a Google Drive '
          'endpoint file configured.',
        );
      }

      if (!cityProfile.distribution.firebaseEnabled) {
        return;
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
    return FutureBuilder<void>(
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
                      const Text(
                        '起動に失敗しました',
                        style: TextStyle(
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
                        child: const Text('再試行'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          );
        }

        final cityProfile = ref.watch(cityProfileProvider);
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
