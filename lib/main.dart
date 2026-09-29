import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/app_clock.dart';
import 'l10n/app_localizations.dart';
import 'l10n/city_localizations.dart';
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
      onGenerateTitle: (context) => localizedCityAppName(
        AppLocalizations.of(context),
        cityProfile.city,
      ),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      builder: (context, child) => ScaffoldMessenger(child: child!),
      home: const RootGate(),
    );
  }
}
