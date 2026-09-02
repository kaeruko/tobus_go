import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_core/firebase_core.dart';

import 'api_endpoint_source.dart';
import 'constants.dart';
import 'firebase_options.dart';
import 'root_gate.dart';
import 'providers/app_session_provider.dart';
import 'providers/city_profile_provider.dart';
import 'core/app_clock.dart';
import 'core/city_profile.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  appClock.setOffset(const Duration(hours: 0, minutes: 0));

  final container = ProviderContainer();
  // Resolve the native flavor before any external service is initialized.
  final cityProfile = container.read(cityProfileProvider);

  final String explicitApiBase = kApiBaseOverride.trim();
  if (explicitApiBase.isNotEmpty) {
    configureApiBase(parseExplicitApiBaseOverride(explicitApiBase));
  } else if (cityProfile.city == AppCity.tokyo) {
    final Uri apiBaseUri = await loadApiBaseUriFromGoogleDrive(
      googleDriveFileId: kTokyoApiGoogleDriveFileId,
    );
    configureApiBase(apiBaseUri);
  } else {
    throw StateError(
      'No runtime API endpoint source is configured for ${cityProfile.key}. '
      'Provide API_BASE explicitly until this city has its own Google Drive '
      'endpoint file.',
    );
  }

  if (cityProfile.distribution.firebaseEnabled) {
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
        );
      }
    } on FirebaseException catch (e) {
      if (e.code != 'duplicate-app') {
        rethrow;
      }
    }
    await container.read(appSessionProvider.notifier).initialize();
  }

  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const App(),
    ),
  );
}

class App extends ConsumerWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cityProfile = ref.watch(cityProfileProvider);

    return CupertinoApp(
      debugShowCheckedModeBanner: false,
      title: cityProfile.appName,
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [
        Locale('ja', 'JP'),
      ],
      builder: (context, child) => ScaffoldMessenger(child: child!),
      home: const RootGate(),
    );
  }
}
