import 'package:flutter/cupertino.dart';
import 'home_page.dart';
import 'live_page.dart';
import 'my_route_page.dart';
import 'settings_page.dart'; // ★追加

class RootTabs extends StatefulWidget {
  const RootTabs({super.key});

  @override
  State<RootTabs> createState() => _RootTabsState();
}

class _RootTabsState extends State<RootTabs> {
  int _currentIndex = 0;
  final List<GlobalKey<NavigatorState>> _navigatorKeys = [
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(),
    GlobalKey<NavigatorState>(), // ★追加
  ];

  @override
  Widget build(BuildContext context) {
    return CupertinoTabScaffold(
      tabBar: CupertinoTabBar(
        currentIndex: _currentIndex,
        onTap: (index) {
          // 同じタブをタップした場合、ナビゲーションスタックをルートまでポップ
          if (index == _currentIndex) {
            _navigatorKeys[index].currentState?.popUntil((route) => route.isFirst);
          }
          setState(() {
            _currentIndex = index;
          });
        },
        items: const [
          BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.search),
            label: '検索',
          ),
          BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.time),
            label: 'ライブ',
          ),
          BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.bookmark),
            label: 'My Route',
          ),
          BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.settings),
            label: '設定',
          ), // ★追加
        ],
      ),
      tabBuilder: (context, index) {
        switch (index) {
          case 0:
            return CupertinoTabView(
              navigatorKey: _navigatorKeys[0],
              builder: (context) => const HomePage(),
            );
          case 1:
            return CupertinoTabView(
              navigatorKey: _navigatorKeys[1],
              builder: (context) => const LivePage(),
            );
          case 2:
            return CupertinoTabView(
              navigatorKey: _navigatorKeys[2],
              builder: (context) => const MyRoutePage(),
            );
          case 3: // ★追加
            return CupertinoTabView(
              navigatorKey: _navigatorKeys[3],
              builder: (context) => const SettingsPage(),
            );
          default:
            return CupertinoTabView(
              navigatorKey: _navigatorKeys[0],
              builder: (context) => const HomePage(),
            );
        }
      },
    );
  }
}
