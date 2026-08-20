import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'pages/root_tabs.dart';
import 'pages/member_mode_page.dart';
import 'providers/app_session_provider.dart';
import 'providers/city_profile_provider.dart';

class RootGate extends ConsumerWidget {
  const RootGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appSession = ref.watch(appSessionProvider);
    final cityProfile = ref.watch(cityProfileProvider);

    if (appSession.isMemberMode) {
      if (!cityProfile.capabilities.features.groupTrips) {
        throw StateError(
          'Member mode is not supported for APP_CITY=${cityProfile.key}',
        );
      }
      return const MemberModePage();
    }

    return const RootTabs();
  }
}
