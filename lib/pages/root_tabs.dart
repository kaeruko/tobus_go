import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/cupertino.dart';
import 'home_page.dart';
import 'my_route_page.dart';
import 'settings_page.dart';
import '../services/trip_service.dart';
import 'history_page.dart';
import 'explore_page.dart';
import '../providers/navigation_provider.dart';

class RootTabs extends ConsumerStatefulWidget {
  const RootTabs({super.key});

  @override
  ConsumerState<RootTabs> createState() => _RootTabsState();
}

class _RootTabsState extends ConsumerState<RootTabs> {
  bool _canShowHistory = false;
  late CupertinoTabController _controller;

  // ナビゲーターキー
  final List<GlobalKey<NavigatorState>> _navigatorKeys = [
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
  ];

  @override
  void initState() {
    super.initState();
    _controller = CupertinoTabController();
    _checkHistoryPermission();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _checkHistoryPermission() async {
    final hasCreated = await TripService().hasCreatedTrip();
    if (mounted) {
      setState(() {
        _canShowHistory = hasCreated;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final currentIndex = ref.watch(tabIndexProvider);
    print('[RootTabs] build called, currentIndex=$currentIndex');

    // Sync controller with provider state
    if (_controller.index != currentIndex) {
       // Microtask to avoid build-phase setState issues in controller
       Future.microtask(() {
         if (mounted) _controller.index = currentIndex;
       });
    }

    // 表示するタブのリストを構築
    final tabs = <BottomNavigationBarItem>[
      const BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.search),
        label: '検索',
      ),
      const BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.compass),
        label: '探索',
      ),
       const BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.bookmark),
        label: 'My Route',
      ),
      if (_canShowHistory)
        const BottomNavigationBarItem(
          icon: Icon(CupertinoIcons.clock),
          label: '履歴',
        ),
      const BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.settings),
        label: '設定',
      ),
    ];

    return CupertinoTabScaffold(
      controller: _controller,
      tabBar: CupertinoTabBar(
        onTap: (index) {
          if (index == _controller.index) {
            _navigatorKeys[index].currentState?.popUntil((route) => route.isFirst);
          }
          ref.read(tabIndexProvider.notifier).state = index;
        },
        items: tabs,
      ),
      tabBuilder: (context, index) {
        if (_canShowHistory) {
           switch (index) {
            case 0: return _buildPage(0, const HomePage());
            case 1: return _buildPage(1, const ExplorePage());
            case 2: return _buildPage(2, const MyRoutePage());
            case 3: return _buildPage(3, const HistoryPage());
            case 4: return _buildPage(4, const SettingsPage());
            default: return _buildPage(0, const HomePage());
          }
        } else {
           switch (index) {
            case 0: return _buildPage(0, const HomePage());
            case 1: return _buildPage(1, const ExplorePage());
            case 2: return _buildPage(2, const MyRoutePage());
            case 3: return _buildPage(3, const SettingsPage());
            default: return _buildPage(0, const HomePage());
          }
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