import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/city_profile.dart';

void main() {
  test('realtime polling defaults to 180 seconds', () {
    expect(kRealtimePollIntervalSeconds, 180);
    expect(kRealtimePollInterval, const Duration(seconds: 180));
  });

  test('realtime transfer warning grace defaults to 300 seconds', () {
    expect(kRealtimeTransferWarningGraceSeconds, 300);
    expect(kRealtimeTransferWarningGrace, const Duration(seconds: 300));
  });

  test('Tokyo uses the runtime config Drive file', () {
    expect(
      runtimeConfigGoogleDriveFileIdForCity(AppCity.tokyo),
      kTokyoRuntimeConfigGoogleDriveFileId,
    );
  });

  test('Tokyo uses its city-specific Google Drive endpoint file', () {
    expect(
      apiGoogleDriveFileIdForCity(AppCity.tokyo),
      kTokyoApiGoogleDriveFileId,
    );
  });

  test('pending Sendai retains its isolated endpoint configuration', () {
    expect(runtimeConfigGoogleDriveFileIdForCity(AppCity.sendai), isNull);
    expect(
      apiGoogleDriveFileIdForCity(AppCity.sendai),
      kSendaiApiGoogleDriveFileId,
    );
  }, tags: 'sendai');

}
