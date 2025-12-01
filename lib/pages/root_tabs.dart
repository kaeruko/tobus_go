import 'package:flutter/cupertino.dart';
import 'home_page.dart';
import 'live_page.dart';
import 'my_route_page.dart';

class RootTabs extends StatelessWidget {
  const RootTabs({super.key});

  @override
  Widget build(BuildContext context) {
    return CupertinoTabScaffold(
      tabBar: CupertinoTabBar(
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
        ],
      ),
      tabBuilder: (context, index) {
        switch (index) {
          case 0:
            return CupertinoTabView(builder: (context) => const HomePage());
          case 1:
            return CupertinoTabView(builder: (context) => const LivePage());
          case 2:
            return CupertinoTabView(builder: (context) => const MyRoutePage());
          default:
            return CupertinoTabView(builder: (context) => const HomePage());
        }
      },
    );
  }
}
