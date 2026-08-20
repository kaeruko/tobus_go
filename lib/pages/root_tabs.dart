import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/navigation_provider.dart';
import 'home_page.dart';
import 'settings_page.dart';

/// Nagoya transit-only shell.
///
/// The Nagoya edition intentionally exposes only route search and settings.
/// Explore, favorites, history, and group outing features remain outside this
/// navigation tree and cannot be reached from the app shell.
class RootTabs extends ConsumerStatefulWidget {
  const RootTabs({super.key});

  @override
  ConsumerState<RootTabs> createState() => _RootTabsState();
}

class _RootTabsState extends ConsumerState<RootTabs> {
  late CupertinoTabController _controller;

  final List<GlobalKey<NavigatorState>> _navigatorKeys = [
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
  ];

  @override
  void initState() {
    super.initState();
    _controller = CupertinoTabController();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final currentIndex = ref.watch(tabIndexProvider);

    const tabs = <BottomNavigationBarItem>[
      BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.search),
        label: '乗換案内',
      ),
      BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.settings),
        label: '設定',
      ),
    ];

    final maxIndex = tabs.length - 1;
    final safeIndex = currentIndex < 0
        ? 0
        : (currentIndex > maxIndex ? maxIndex : currentIndex);

    if (_controller.index != safeIndex) {
      Future.microtask(() {
        if (!mounted) return;
        if (_controller.index != safeIndex) {
          _controller.index = safeIndex;
        }
      });
    }

    if (currentIndex != safeIndex) {
      Future.microtask(() {
        if (!mounted) return;
        if (ref.read(tabIndexProvider) != safeIndex) {
          ref.read(tabIndexProvider.notifier).state = safeIndex;
        }
      });
    }

    return CupertinoTabScaffold(
      controller: _controller,
      tabBar: CupertinoTabBar(
        onTap: (index) {
          if (index == _controller.index) {
            _navigatorKeys[index].currentState?.popUntil(
              (route) => route.isFirst,
            );
          }
          ref.read(tabIndexProvider.notifier).state = index;
        },
        items: tabs,
      ),
      tabBuilder: (context, index) {
        switch (index) {
          case 0:
            return _buildPage(0, const HomePage(title: '名古屋でGO'));
          case 1:
            return _buildPage(1, const SettingsPage());
          default:
            throw StateError('Unexpected Nagoya tab index: $index');
        }
      },
    );
  }

  Widget _buildPage(int index, Widget page) {
    return CupertinoTabView(
      navigatorKey: _navigatorKeys[index],
      builder: (context) => page,
    );
  }
}
