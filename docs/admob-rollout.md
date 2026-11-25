# Tokyo AdMob rollout — local testing only

The app-ads.txt ownership check is independent of local testing. The native
app IDs and banner unit IDs are Google's published samples; no publisher ad
unit is requested. Existing Firebase advertising consent settings and Android
AD_ID removal remain unchanged. No location, route or search text is passed
in the test request.

## Local debug test

```powershell
flutter pub get
flutter run --flavor tokyo --dart-define=APP_CITY=tokyo --dart-define=TOEIGO_TEST_ADS=true
```

Use an Android device/emulator or an iOS device/simulator with the usual
platform-specific Maps setup. Search for a route and scroll to the bottom
of the successful results. Expect one 320x50 Google test banner, separated
from route cards. No ad on empty results, loading, errors, or detail/navigation
screens. Without the explicit define, or in profile/release, there is no
Dart ad initialization or request. Network or SDK failure is logged and
does not retry through another ad source.

## Distribution gate

Store AAB and TestFlight scripts are intentionally blocked until the native
sample IDs are replaced and production privacy/configuration is complete.
The CI-only Android release build uses a validation signing key and explicit
ValidationOnly switch; it is never for distribution. Do not manually upload
any artifact from this stage. The existing already-uploaded version is
unaffected.

Before enabling distribution:

- Obtain both platform-specific AdMob app IDs and banner unit IDs.
- Complete ownership/readiness checks; create privacy messages in AdMob.
- Implement UMP consent update on launch, required forms, canRequestAds gate,
  and settings entry for privacy options if required. Do not request ads when
  consent update or form fails. Do not request ATT or enable AD_ID unless
  separately agreed and privacy disclosures are updated.
- Replace sample native IDs, verify required iOS SKAdNetwork entries, and
  update app privacy policy, App Store privacy details, Google Play data
  safety and contains-ads declaration based on actual SDK data use.
- Separate development/test units from production units. Confirm on devices
  (including dark mode, narrow screens, route errors and navigation), review
  merged manifests, run CI, commit generated dependency locks, then remove
  distribution guards as part of the reviewed production change.

Official guides:
- https://developers.google.com/admob/flutter/quick-start
- https://developers.google.com/admob/flutter/test-ads
- https://developers.google.com/admob/flutter/privacy
- https://codelabs.developers.google.com/codelabs/admob-ads-in-flutter
