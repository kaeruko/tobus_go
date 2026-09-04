import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/city_profile.dart';

void main() {
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
