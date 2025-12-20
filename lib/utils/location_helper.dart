import 'package:geolocator/geolocator.dart';

class LocationHelper {
  /// 現在の緯度経度を "lat,lon" 形式の文字列で取得する。
  /// 権限がない場合は要求し、拒否された場合はエラーを投げる。
  static Future<String> getCurrentLocationString() async {
    bool serviceEnabled;
    LocationPermission permission;

    // Test if location services are enabled.
    serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      throw Exception('位置情報サービスが無効です。');
    }

    permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        throw Exception('位置情報の権限が拒否されました。');
      }
    }

    if (permission == LocationPermission.deniedForever) {
      throw Exception('位置情報の権限が永久に拒否されています。設定から許可してください。');
    }

    // When we reach here, permissions are granted and we can
    // continue accessing the position of the device.
    final position = await Geolocator.getCurrentPosition();
    return '${position.latitude},${position.longitude}';
  }
}
