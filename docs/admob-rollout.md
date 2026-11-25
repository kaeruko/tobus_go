# Tokyo AdMob rollout — publisher IDs configured, distribution gated

The Android and iOS native app IDs are now the actual Tokyo publisher IDs.
The test banner units remain Google's published sample units; no publisher
unit is used in debug/profile builds. Existing Firebase advertising consent
settings and Android AD_ID removal remain unchanged. ATT is not requested.
No coordinates, route or search text is passed in the ad request.
Requests specify non-personalized ads; this does not eliminate SDK data
collection or the need for consent and store disclosure.

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
error, ads remain disabled, without automatic retry or switch to layout
test mode. Verify on Android and iOS, including required consent regions
using UMP test-device/debug geography configuration before release.

## Distribution gate

The publisher ad units are wired, but require BOTH a release build and
explicit TOEIGO_PRODUCTION_ADS=true plus a successful UMP permission check.
Do not use the release define for local testing. Store AAB and TestFlight
scripts remain blocked pending review. CI builds validation artifacts with
no production ad define, and must never be distributed.

Before enabling distribution:

- Confirm both apps' ownership and serving readiness in AdMob.
- Publish applicable privacy messages and verify UMP with the real app IDs,
  including required form, no-consent and failure paths, privacy options.
- Verify iOS device behavior and Android merged manifest, including no
  AD_ID permission; review SDK privacy manifests and SKAdNetwork list.
- Publish the actual app privacy policy; update App Store privacy details,
  Google Play data safety and contains-ads declarations based on actual SDK
  data use. Non-personalized ads are not equivalent to no data collection.
- Commit generated dependency lockfiles from a successful resolution.
- After approval, remove distribution guards and explicitly pass the
  production define in reviewed store build scripts, not in debug builds.

Official guides:
- https://developers.google.com/admob/flutter/quick-start
- https://developers.google.com/admob/flutter/test-ads
- https://developers.google.com/admob/flutter/privacy
- https://developers.google.com/admob/ios/quick-start
- https://developers.google.com/admob/ios/privacy/data-disclosure
- https://developers.google.com/admob/android/privacy/play-data-disclosure

## Privacy policy review before release

The existing pages `https://cloxs.jp/toeigo/privacy.html` and
`https://cloxs.jp/toeigo_privacy.html` already mention AdMob, but only
in a general third-party services paragraph. Update the actual store-linked
policy (and keep both copies consistent) before distribution. Draft text for
review, not yet published:

> 当アプリは運営費の一部を賄うため Google AdMob による広告を表示します。
> 広告配信、表示・クリックの計測、不正防止等のため、Google が IP アドレス、
> 端末・アプリ情報、広告とのやり取り、診断情報、利用可能な識別子等を処理する
> 場合があります。経路検索の出発地・目的地や現在地の座標を広告リクエストの
> パラメータとして送信することはありません。広告のプライバシー設定が必要な
> 地域では、同意画面およびアプリの設定から選択を変更できます。
> Google による情報の利用については
> https://policies.google.com/technologies/partner-sites をご確認ください。

Verify the final SDK data disclosure, identifiers, consent configuration and
actual app behavior before publishing this draft. Also review the existing
policy's location, route search, group trip and analytics disclosures; this
ad-specific draft alone is not a full audit of the policy.
