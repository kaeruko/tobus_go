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
platform-specific Maps setup. Search for a route. Expect one Google test banner fixed above the tab bar,
separated from route cards and tabs. No ad on empty results, loading, errors,
keyboard open, other tabs or detail/navigation screens. Without the explicit define, or in profile/release, there is no
Dart ad initialization or request. Network or SDK failure is logged and
does not retry through another ad source.

## UMP test mode (separate from layout testing)

```powershell
flutter run --flavor tokyo --dart-define=APP_CITY=tokyo --dart-define=TOEIGO_TEST_ADS=true --dart-define=TOEIGO_TEST_UMP=true
```

The UMP test path updates consent when RootTabs is first shown, presents any
required form, then checks canRequestAds. Settings shows the privacy options
entry when required. On any UMP error the ad remains disabled; there is no
automatic retry or switch to the layout-only mode. Google's sample app ID
may not have a usable publisher privacy message; real-ID consent testing is
still required. Both modes use sample banner units only.

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
- Enable the prepared UMP flow for real ads, remove the test-only flag for
  production, verify the actual privacy message and consent in target regions.
  Do not request ATT or enable AD_ID unless separately agreed and privacy
  disclosures are updated.
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
