import 'package:flutter_riverpod/flutter_riverpod.dart';

final tabIndexProvider = StateProvider<int>((ref) => 0);

final searchTabRootRequestProvider = StateProvider<int>((ref) => 0);

void requestSearchTabRoot(WidgetRef ref) {
  ref.read(tabIndexProvider.notifier).state = 0;
  final request = ref.read(searchTabRootRequestProvider.notifier);
  request.state = request.state + 1;
}
