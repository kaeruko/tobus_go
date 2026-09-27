import 'package:flutter/cupertino.dart';

import '../core/city_profile.dart';

const String _tokyoHeaderLogoAsset = 'assets/icon/tokyo.png';

CupertinoNavigationBar buildAppNavigationBar({
  required Widget middle,
  Widget? leading,
  Widget? trailing,
  bool automaticallyImplyLeading = true,
}) {
  return CupertinoNavigationBar(
    automaticallyImplyLeading: automaticallyImplyLeading,
    leading: leading,
    middle: middle,
    trailing: trailing,
  );
}

Widget cityBrandNavigationTitle({
  required AppCity city,
  required String fallbackTitle,
}) {
  switch (city) {
    case AppCity.tokyo:
      return Semantics(
        label: fallbackTitle,
        child: Image.asset(
          _tokyoHeaderLogoAsset,
          height: 34,
          fit: BoxFit.contain,
          filterQuality: FilterQuality.medium,
          excludeFromSemantics: true,
        ),
      );
    case AppCity.nagoya:
    case AppCity.sendai:
    case AppCity.yokohama:
      return Text(fallbackTitle);
  }
}
