# Tokyo AdMob rollout — production release enabled

The Android and iOS native app IDs are now the actual Tokyo publisher IDs.
The test banner units remain Google's published sample units; no publisher
unit is used in debug/profile builds. Firebase advertising consent settings
default to denied. Android excludes both advertising ID permissions. ATT is
not requested.
No coordinates, route or search text is passed in the ad request.
Requests specify non-personalized ads; this does not eliminate SDK data
collection or the need for consent and store disclosure.

| Platform | Store identifier | Native AdMob app ID | Production banner unit ID |
| --- | --- | --- | --- |
| Android | `jp.cloxs.toeigo` | `ca-app-pub-1701253412237513~1176167982` | `ca-app-pub-1701253412237513/5953725636` |
| iOS | `jp.cloxs.go.tokyo` | `ca-app-pub-1701253412237513~2728475696` | `ca-app-pub-1701253412237513/2050652992` |

## Local debug test

```powershell
flutter pub get
flutter run --flavor tokyo --dart-define=APP_CITY=tokyo --dart-define=TOEIGO_TEST_ADS=true
```

Search for a route. One Google test banner is fixed above the tab bar.
No ad on empty results, loading, errors, keyboard open, other tabs or detail
navigation screens. SDK failures are logged without alternate ad sources.

## Test UMP against actual publisher app ID

First configure and publish privacy messages in the AdMob console for both
apps. This mode tests UMP with the actual native app ID, but still requests
only Google's sample banner units.

```powershell
flutter run --flavor tokyo --dart-define=APP_CITY=tokyo --dart-define=TOEIGO_TEST_ADS=true --dart-define=TOEIGO_TEST_UMP=true
```

On RootTabs startup, update consent, show any required form, then check
canRequestAds. Settings exposes privacy options if required. On any UMP
error or unknown privacy-options status, ads remain disabled for that attempt.
The app does not automatically retry or switch to layout test mode.

Use the device hash printed by UMP in the first run's native logs to force a
region on a test device. Use a fresh test installation or reset the test app's
data between first-launch cases. Keep the device hash out of tracked files.

```powershell
flutter run --flavor tokyo --dart-define=APP_CITY=tokyo --dart-define=TOEIGO_TEST_ADS=true --dart-define=TOEIGO_TEST_UMP=true --dart-define=TOEIGO_TEST_UMP_GEOGRAPHY=eea --dart-define=TOEIGO_TEST_UMP_DEVICE_ID=YOUR_UMP_DEVICE_HASH
```

Both geography and device hash are required when forcing a region. Supported
geographies are `eea`, `regulated-us`, and `other`. These settings apply only
in the opt-in debug UMP mode and keep the sample banner units.

Verify on Android and iOS devices:

- In a region with a published message, verify the first-launch form, acceptance,
  refusal and changing or withdrawing the choice from Settings. Check that no
  banner request is made when `canRequestAds` is false. A refusal can still allow
  limited ads depending on what UMP permits.
- With connectivity disabled at launch, verify that a UMP failure keeps ads
  off even if the app had a prior decision. For this isolated debug test, add
  `--dart-define=API_BASE=https://example.invalid` to reach RootTabs without a
  Google Drive bootstrap request. Verify a region without a required message
  as well.
- Verify a single banner below populated search results. Check the hidden states
  above, and on iOS verify app startup and the absence of an ATT prompt.

## Distribution gate

The publisher ad units are wired, but require BOTH a release build and
explicit TOEIGO_PRODUCTION_ADS=true plus a successful UMP permission check.
Do not use the release define for local testing. Following the maintainer's
release authorization on 2026-11-27, Tokyo store AAB and TestFlight builds
explicitly enable production ads. CI validation builds disable production
ads and must never be distributed. Sendai remains blocked. UMP failure
still disables ads.

Release review checklist (release authorization does not establish that all external checks are complete):

- Confirm both apps' ownership and serving readiness in AdMob. Match each app
  and its banner unit to the table above, including the linked store listing.
- Publish applicable privacy messages and verify UMP with the real app IDs,
  including required form, no-consent and failure paths, privacy options.
- Verify iOS device behavior and review the SDK privacy manifests and
  SKAdNetwork list. The Android AAB CI job checks the packaged manifest for
  `com.google.android.gms.permission.AD_ID`,
  `android.permission.ACCESS_ADSERVICES_AD_ID`, and the expected AdMob app ID.
- Publish the actual app privacy policy; update App Store privacy details,
  Google Play data safety and contains-ads declarations based on actual SDK
  data use. Non-personalized ads are not equivalent to no data collection.
- Commit generated dependency lockfiles from a successful resolution.
  `pubspec.lock` already records `google_mobile_ads`. Regenerate `ios/Podfile.lock`
  on macOS from a successful iOS build and review the resolved Ads and UMP
  privacy manifests before approving the release.
- Confirm that store builds explicitly enable production ads and that
  debug and CI validation builds do not enable production ads.

### AdMob console verification

On 2026-11-26, AdMob showed both Tokyo apps as ready with ad serving enabled.
The Android app linked to `jp.cloxs.toeigo` on Google Play and the iOS app
linked to App Store ID `6804165349`. Each listed a single active banner whose
unit ID matches the table above. `tokyo_gdpr_consent` and `tokyo_us_privacy`
were published in English for both apps. Both apps used the same policy URL
in the European message. [AdMob app list](https://admob.google.com/v2/apps/list) ·
[AdMob privacy messages](https://admob.google.com/v2/privacymessaging)

The European account settings listed the automatically included common
ad partners (199 in the settings view), legitimate-interest controls on by
default, and advertising Consent Mode off. Review the partner list and the
message purposes against actual SDK use before enabling distribution.

### Android emulator verification

On 2026-11-26, the real Android app ID returned an EEA consent form on an
emulator. The form could be reopened from Settings after saving choices.
The sample banner appeared once below populated search results after the
keyboard closed. It was hidden with the keyboard open and on route detail.
An offline launch with the debug API override and a saved UMP decision
stopped at the UMP update error. The validation AAB excluded both advertising
ID permissions.

The validation AAB resolved Google Mobile Ads 25.5.0 and UMP 4.0.0. Its merged
manifest still includes the SDK's Topics and Attribution Reporting permissions.
Account for these when reviewing Android's advertising data use and store
declarations. [Google's Privacy Sandbox guide](https://developers.google.com/admob/android/privacy/sandbox)

The EEA form's first screen showed `Consent` and `Manage options` and described
personalized advertising, precise location and 210 ad partners. Review the
first-screen refusal option, partner list, purposes and Firebase Consent Mode
settings in AdMob against actual app data use and the non-personalized banner
request. Repeat the check with each published message before distribution.
[AdMob European regulations message settings](https://support.google.com/admob/answer/10113207) ·
[AdMob ad partner settings](https://support.google.com/admob/answer/10113004) ·
[AdMob Consent Mode settings](https://support.google.com/admob/answer/16053245)

With regulated US geography forced, the emulator opened the opt-out form
from Settings and retained the opt-out when reopened. The published English
form describes interest-based ads for users who allow sale or sharing. Review
that wording against the app's non-personalized banner requests as well.
With `other` forced on a fresh install, the app started without a form or UMP
error, and Settings did not display the ad privacy entry.

Official guides:
- https://developers.google.com/admob/flutter/quick-start
- https://developers.google.com/admob/flutter/test-ads
- https://developers.google.com/admob/flutter/privacy
- https://developers.google.com/admob/ios/quick-start
- https://developers.google.com/admob/ios/privacy/data-disclosure
- https://developers.google.com/admob/android/privacy/play-data-disclosure

## Privacy policy review before release

On 2026-11-26, both public policy pages included ad data use and UMP settings.
The public `app-ads.txt` listed publisher `pub-1701253412237513`.
[Privacy policy](https://cloxs.jp/toeigo/privacy.html) ·
[Second copy](https://cloxs.jp/toeigo_privacy.html) ·
[app-ads.txt](https://cloxs.jp/app-ads.txt)

Verify the policy links and disclosures in both store consoles and review
the data use of the resolved SDK versions.
Google Mobile Ads for iOS 13.12.0 and later enables SDK collection of coarse
device location by default when the app has location permission. Review that
setting and the corresponding policy and store disclosures against the actual
resolved SDK and app. See [Google's iOS targeting guide](https://developers.google.com/admob/ios/targeting#collect_coarse_location).

### Store console verification

- App Store Connect shows published privacy details and the expected policy URL.
  Third-party advertising is listed for device ID, product interaction,
  advertising data, crash data and performance data. The vendor privacy
  manifests for Google Mobile Ads 13.13.0 list third-party advertising for
  coarse location and other diagnostic data as well. Compare those purposes
  with the actual version bundled by CocoaPods, the app settings and the store
  answers. Review coarse location derived from IP addresses and the app's use
  of the SDK's device-location setting. [App Store Connect privacy](https://appstoreconnect.apple.com/apps/6804165349/distribution/privacy) ·
  [Google's iOS disclosures](https://developers.google.com/admob/ios/privacy/data-disclosure)
- Play Console declares that the app contains ads. The new policy URL and Data
  safety answers are approved and awaiting managed publishing alongside version
  `1.0.40` (`54`). The exported answers mark encryption in transit as `false`,
  app interactions as collected only, and approximate location as shared for
  app functionality only. Google documents transit encryption for the Ads SDK
  and lists app interactions among the data it collects and shares. The release
  AAB does not opt into Android cleartext traffic, and release API endpoints
  require HTTPS. Verify encryption for all SDK data flows and reconcile the
  advertising purposes before publishing the declaration for an ad-enabled
  build. Check the separate Advertising ID declaration against the release AAB.
  [Google's Android disclosures](https://developers.google.com/admob/android/privacy/play-data-disclosure)
