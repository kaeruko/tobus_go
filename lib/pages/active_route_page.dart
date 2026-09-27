import 'package:flutter/cupertino.dart';

import '../core/city_profile.dart';
import '../l10n/app_localizations.dart';
import '../l10n/city_localizations.dart';
import '../models/route_models.dart';
import '../services/bus_location_source.dart';
import '../widgets/active_route_content.dart';
import '../widgets/app_navigation_bar.dart';

class ActiveRoutePage extends StatelessWidget {
  final Candidate candidate;
  final CityProfile cityProfile;
  final BusLocationSource? busLocationSource;

  ActiveRoutePage({
    super.key,
    required this.candidate,
    CityProfile? cityProfile,
    this.busLocationSource,
  }) : cityProfile = cityProfile ?? configuredCityProfile;

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: buildAppNavigationBar(
        middle: cityBrandNavigationTitle(
          city: cityProfile.city,
          fallbackTitle: localizedCityAppName(
            AppLocalizations.of(context),
            cityProfile.city,
          ),
        ),
      ),
      child: SafeArea(
        child: ActiveRouteContent(
          candidate: candidate,
          cityProfile: cityProfile,
          busLocationSource: busLocationSource,
          onEnd: () => Navigator.of(context).pop(),
        ),
      ),
    );
  }
}
