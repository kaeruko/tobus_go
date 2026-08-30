import 'package:flutter/cupertino.dart';

import '../core/city_profile.dart';
import '../models/route_models.dart';
import '../services/bus_location_source.dart';
import '../widgets/active_route_content.dart';

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
      navigationBar: const CupertinoNavigationBar(middle: Text('移動中')),
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
