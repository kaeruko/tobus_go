import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/app_clock.dart';
import 'providers/city_profile_provider.dart';
import 'root_gate.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  appClock.setOffset(const Duration(hours: 0, minutes: 0));

  final container = ProviderContainer();

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
