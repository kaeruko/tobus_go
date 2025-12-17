import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/cupertino.dart';
import 'home_page.dart';
import 'my_route_page.dart';
import 'settings_page.dart';
import '../services/trip_service.dart';
import 'history_page.dart';
import 'explore_page.dart'; // インポート済み

class RootTabs extends StatefulWidget {
  const RootTabs({super.key});

  @override
  State<RootTabs> createState() => _RootTabsState();
}

class _RootTabsState extends State<RootTabs> {
  int _currentIndex = 0;
  bool _canShowHistory = false; // 履歴タブを表示するかどうか

  // ナビゲーターキー (最大5つ分確保しておく: Home, Explore, MyRoute, History, Settings)
  final List<GlobalKey<NavigatorState>> _navigatorKeys = [
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(), // ★追加
  ];

  final ValueNotifier<int> _tabNotifier = ValueNotifier(0);

  @override
  void initState() {
    super.initState();
    _checkHistoryPermission();
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
    // 表示するタブのリストを構築
    final tabs = <BottomNavigationBarItem>[
      const BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.search),
        label: '検索',
      ),
      // ★追加: 探索タブ
      const BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.compass), // コンパスアイコンなどが探索っぽい
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
      tabBar: CupertinoTabBar(
        currentIndex: _currentIndex,
        onTap: (index) {
          if (index == _currentIndex) {
            _navigatorKeys[index].currentState?.popUntil((route) => route.isFirst);
          }
          setState(() {
            _currentIndex = index;
            _tabNotifier.value = index;
          });
        },
        items: tabs,
      ),
      tabBuilder: (context, index) {
        // インデックスとページの対応付けを修正
        // Exploreが入ったので、それ以降のインデックスが1つずつずれます

        if (_canShowHistory) {
          // 履歴あり: 0:Home, 1:Explore, 2:MyRoute, 3:History, 4:Setting
           switch (index) {
            case 0: return _buildPage(0, HomePage(tabIndexListenable: _tabNotifier));
            case 1: return _buildPage(1, const ExplorePage()); // ★追加
            case 2: return _buildPage(2, const MyRoutePage());
            case 3: return _buildPage(3, const HistoryPage());
            case 4: return _buildPage(4, const SettingsPage());
            default: return _buildPage(0, HomePage(tabIndexListenable: _tabNotifier));
          }
        } else {
          // 履歴なし: 0:Home, 1:Explore, 2:MyRoute, 3:Setting
           switch (index) {
            case 0: return _buildPage(0, HomePage(tabIndexListenable: _tabNotifier));
            case 1: return _buildPage(1, const ExplorePage()); // ★追加
            case 2: return _buildPage(2, const MyRoutePage());
            case 3: return _buildPage(3, const SettingsPage());
            default: return _buildPage(0, HomePage(tabIndexListenable: _tabNotifier));
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