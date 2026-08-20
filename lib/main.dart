import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_core/firebase_core.dart';

import 'firebase_options.dart';
import 'root_gate.dart';
import 'providers/app_session_provider.dart';
import 'providers/city_profile_provider.dart';
import 'core/app_clock.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  appClock.setOffset(const Duration(hours: 0, minutes: 0));

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

  final container = ProviderContainer();
  // Resolve APP_CITY before startup so an unknown city fails fast.
  container.read(cityProfileProvider);
  await container.read(appSessionProvider.notifier).initialize();

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
