import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/city_profile_provider.dart';
import '../providers/navigation_provider.dart';
import 'explore_page.dart';
import 'fare_policy_settings_page.dart';
import 'history_page.dart';
import 'home_page.dart';
import 'my_route_page.dart';
import 'route_only_home_page.dart';

class RootTabs extends ConsumerStatefulWidget {
  const RootTabs({super.key});

  @override
  ConsumerState<RootTabs> createState() => _RootTabsState();
}

class _RootTabEntry {
  final BottomNavigationBarItem item;
  final Widget page;

  const _RootTabEntry({required this.item, required this.page});
}

class _RootTabsState extends ConsumerState<RootTabs> {
  late CupertinoTabController _controller;

  final List<GlobalKey<NavigatorState>> _navigatorKeys = List.generate(
    5,
    (_) => GlobalKey<NavigatorState>(),
  );

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

  List<_RootTabEntry> _buildEntries() {
    final cityProfile = ref.watch(cityProfileProvider);
    final features = cityProfile.capabilities.features;
    final searchPage = features.routeSearchOnly
        ? RouteOnlyHomePage(title: cityProfile.appName)
        : HomePage(title: cityProfile.appName);

    return [
      _RootTabEntry(
        item: const BottomNavigationBarItem(
          icon: Icon(CupertinoIcons.search),
          label: '検索',
        ),
        page: searchPage,
      ),
      if (features.outingDiscovery)
        const _RootTabEntry(
          item: BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.compass),
            label: 'みつける',
          ),
          page: ExplorePage(),
        ),
      if (features.savedRoutes)
        const _RootTabEntry(
          item: BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.bookmark),
            label: 'お気に入り',
          ),
          page: MyRoutePage(),
        ),
      if (features.history)
        const _RootTabEntry(
          item: BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.clock),
            label: '履歴',
          ),
          page: HistoryPage(),
        ),
      const _RootTabEntry(
        item: BottomNavigationBarItem(
          icon: Icon(CupertinoIcons.settings),
          label: '設定',
        ),
        page: FarePolicySettingsPage(),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final currentIndex = ref.watch(tabIndexProvider);
    final entries = _buildEntries();

    if (entries.isEmpty) {
      throw StateError('RootTabs requires at least one enabled tab');
    }
    if (entries.length > _navigatorKeys.length) {
      throw StateError(
        'RootTabs has ${entries.length} tabs but only '
        '${_navigatorKeys.length} navigator keys',
      );
    }

    final maxIndex = entries.length - 1;
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
        final now = ref.read(tabIndexProvider);
        if (now != safeIndex) {
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
        items: entries.map((entry) => entry.item).toList(growable: false),
      ),
      tabBuilder: (context, index) {
        if (index < 0 || index >= entries.length) {
          throw RangeError.index(index, entries, 'index');
        }
        return _buildPage(index, entries[index].page);
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
