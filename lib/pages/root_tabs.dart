import 'package:flutter/cupertino.dart';
import 'home_page.dart';
import 'live_page.dart';
import 'my_route_page.dart';
import 'settings_page.dart';
import '../services/trip_service.dart';
import 'history_page.dart';

class RootTabs extends StatefulWidget {
  const RootTabs({super.key});

  @override
  State<RootTabs> createState() => _RootTabsState();
}

class _RootTabsState extends State<RootTabs> {
  int _currentIndex = 0;
  bool _canShowHistory = false; // 履歴タブを表示するかどうか

  // ナビゲーターキー (最大5つ分確保しておく)
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
      const BottomNavigationBarItem(
        icon: Icon(CupertinoIcons.time),
        label: 'ライブ',
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
          });
        },
        items: tabs,
      ),
      tabBuilder: (context, index) {
        // インデックスとページの対応付け
        // 履歴がある場合: 0:Home, 1:Live, 2:MyRoute, 3:History, 4:Setting
        // 履歴がない場合: 0:Home, 1:Live, 2:MyRoute, 3:Setting

        if (_canShowHistory) {
           switch (index) {
            case 0: return _buildPage(0, const HomePage());
            case 1: return _buildPage(1, const LivePage());
            case 2: return _buildPage(2, const MyRoutePage());
            case 3: return _buildPage(3, const HistoryPage()); // 履歴
            case 4: return _buildPage(4, const SettingsPage());
            default: return _buildPage(0, const HomePage());
          }
        } else {
           switch (index) {
            case 0: return _buildPage(0, const HomePage());
            case 1: return _buildPage(1, const LivePage());
            case 2: return _buildPage(2, const MyRoutePage());
            case 3: return _buildPage(3, const SettingsPage()); // 設定が3番目に来る
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

