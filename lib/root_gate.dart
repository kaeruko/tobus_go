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
    final cityProfile = ref.watch(cityProfileProvider);

    if (!cityProfile.capabilities.features.groupTrips) {
      return const RootTabs();
    }

    final appSession = ref.watch(appSessionProvider);
    if (appSession.isMemberMode) {
      return const MemberModePage();
    }

    return const RootTabs();
  }
}
