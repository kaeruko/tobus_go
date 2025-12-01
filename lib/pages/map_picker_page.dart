import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

class MapPickerPage extends StatefulWidget {
  final String? title;
  const MapPickerPage({super.key, this.title});
  @override
  State<MapPickerPage> createState() => _MapPickerPageState();
}

class _MapPickerPageState extends State<MapPickerPage> {
  final LatLng _center = const LatLng(35.681236, 139.767125); // 東京駅あたり
  LatLng? _picked;
  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(widget.title ?? '地図から選ぶ'),
      ),
      child: SafeArea(
        child: Stack(
          children: [
            GoogleMap(
              initialCameraPosition: CameraPosition(target: _center, zoom: 13),
              myLocationEnabled: true,
              onLongPress: (latLng) => setState(() => _picked = latLng),
              markers: {
                if (_picked != null)
                  Marker(
                    markerId: const MarkerId('picked'),
                    position: _picked!,
                  ),
              },
            ),
            Positioned(
              left: 16,
              right: 16,
              bottom: 24,
              child: CupertinoButton.filled(
                onPressed: _picked == null
                    ? null
                    : () => Navigator.pop(context, _picked),
                child: Text(_picked == null ? '長押しで地点を選択' : 'この地点を決定'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
