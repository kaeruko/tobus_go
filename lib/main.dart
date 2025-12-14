import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_core/firebase_core.dart';
import 'firebase_options.dart';

import 'root_gate.dart';
import 'providers/app_session_provider.dart';
import 'core/app_clock.dart';

void main() async {
  appClock.setOffset(Duration(hours: 14));

  WidgetsFlutterBinding.ensureInitialized();

  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );

  // Initialize ProviderContainer to load AppSession before app starts
  final container = ProviderContainer();
  await container.read(appSessionProvider.notifier).initialize();

  // Saved Routes are now loaded by the provider on demand.
  
  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const App(),
    ),
  );
}

class App extends StatelessWidget {
  const App({super.key});
  
  @override
  Widget build(BuildContext context) {
    return CupertinoApp(
      debugShowCheckedModeBanner: false,
      title: '都営でGO',
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
