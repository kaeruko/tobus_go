import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../l10n/city_localizations.dart';
import '../providers/city_profile_provider.dart';
import '../providers/navigation_provider.dart';
import 'explore_page.dart';
import 'history_page.dart';
import 'my_route_page.dart';
import 'route_search_page.dart';

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
    4,
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

  List<_RootTabEntry> _buildEntries(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final cityProfile = ref.watch(cityProfileProvider);
    final features = cityProfile.capabilities.features;
    final searchPage = RouteSearchPage(
      title: localizedCityAppName(l10n, cityProfile.city),
    );

    return [
      _RootTabEntry(
        item: BottomNavigationBarItem(
          icon: const Icon(CupertinoIcons.search),
          label: l10n.tabSearch,
        ),
        page: searchPage,
      ),
      if (features.outingDiscovery)
        _RootTabEntry(
          item: BottomNavigationBarItem(
            icon: const Icon(CupertinoIcons.compass),
            label: l10n.tabDiscover,
          ),
          page: const ExplorePage(),
        ),
      if (features.savedRoutes)
        _RootTabEntry(
          item: BottomNavigationBarItem(
            icon: const Icon(CupertinoIcons.bookmark),
            label: l10n.tabFavorites,
          ),
          page: const MyRoutePage(),
        ),
      if (features.history)
        _RootTabEntry(
          item: BottomNavigationBarItem(
            icon: const Icon(CupertinoIcons.clock),
            label: l10n.tabHistory,
          ),
          page: const HistoryPage(),
        ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<int>(searchTabRootRequestProvider, (previous, next) {
      if (previous == next) return;

      if (_controller.index != 0) {
        _controller.index = 0;
      }

      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        final navigator = _navigatorKeys[0].currentState;
        if (navigator == null) {
          throw StateError(
            '検索タブのNavigatorを取得できないため、検索画面へ戻せません',
          );
        }
        navigator.popUntil((route) => route.isFirst);
      });
    });

    final currentIndex = ref.watch(tabIndexProvider);
    final entries = _buildEntries(context);

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
