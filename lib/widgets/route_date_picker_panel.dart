import 'package:flutter/cupertino.dart';

/// Resolve semantic colors before painting non-Cupertino containers.
/// The picker keeps the inherited Cupertino text theme and system brightness.
class RouteDatePickerPanel extends StatelessWidget {
  final double height;
  final Widget child;

  const RouteDatePickerPanel({
    super.key,
    required this.height,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      height: height,
      color: CupertinoDynamicColor.resolve(
        CupertinoColors.systemBackground,
        context,
      ),
      child: child,
    );
  }
}
