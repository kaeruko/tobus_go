import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/city_profile.dart';

void main() {
  test('realtime polling defaults to 60 seconds', () {
    expect(kRealtimePollIntervalSeconds, 60);
    expect(kRealtimePollInterval, const Duration(seconds: 60));
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
    expect(runtimeConfigGoogleDriveFileIdForCity(AppCity.sendai), isNull);
    expect(runtimeConfigGoogleDriveFileIdForCity(AppCity.nagoya), isNull);
    expect(runtimeConfigGoogleDriveFileIdForCity(AppCity.yokohama), isNull);
  });

  test('Tokyo and Sendai use city-specific Google Drive endpoint files', () {
    expect(
      apiGoogleDriveFileIdForCity(AppCity.tokyo),
      kTokyoApiGoogleDriveFileId,
    );
    expect(
      apiGoogleDriveFileIdForCity(AppCity.sendai),
      kSendaiApiGoogleDriveFileId,
    );
  });

  test('cities without a Drive endpoint file keep using API_BASE', () {
    expect(apiGoogleDriveFileIdForCity(AppCity.nagoya), isNull);
    expect(apiGoogleDriveFileIdForCity(AppCity.yokohama), isNull);
  });
}
