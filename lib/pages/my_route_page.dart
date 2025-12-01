import 'package:flutter/cupertino.dart';
import '../data/global_state.dart';
import '../widgets/route_card.dart';
import 'route_detail_page.dart';

class MyRoutePage extends StatefulWidget {
  const MyRoutePage({super.key});

  @override
  State<MyRoutePage> createState() => _MyRoutePageState();
}

class _MyRoutePageState extends State<MyRoutePage> {
  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(
        middle: Text('My Route'),
      ),
      child: SafeArea(
        child: kSavedRoutes.isEmpty
            ? const Center(child: Text('保存された経路はありません'))
            : ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                itemCount: kSavedRoutes.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (context, i) {
                  final c = kSavedRoutes[i];
                  return GestureDetector(
                    onTap: () {
                      Navigator.of(context).push(
                        CupertinoPageRoute(
                          builder: (_) => RouteDetailPage(candidate: c),
                        ),
                      );
                    },
                    child: RouteCard(candidate: c, rank: i + 1),
                  );
                },
              ),
      ),
    );
  }
}
