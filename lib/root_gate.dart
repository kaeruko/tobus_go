import 'package:flutter/material.dart';

import 'pages/root_tabs.dart';

/// Entry point for the Nagoya transit-only edition.
///
/// Group/member outing modes are intentionally not part of this product.
class RootGate extends StatelessWidget {
  const RootGate({super.key});

  @override
  Widget build(BuildContext context) {
    return const RootTabs();
  }
}
