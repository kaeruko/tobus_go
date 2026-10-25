# Tokyo Metro static GTFS release runbook

This is the existing manual release procedure for PR #253. It does not add an
automatic updater and does not authorize a production deployment.

## Accepted source and licence

- Official catalog: <https://ckan.odpt.org/dataset/train-tokyometro>
- Official GTFS resource: <https://ckan.odpt.org/dataset/train-tokyometro/resource/d4f11962-1c5a-4316-9a16-7fb229c227ea>
- ODPT Basic License: <https://developer.odpt.org/terms/data_basic_license.html>
- ODPT Basic-data guideline: <https://developer.odpt.org/terms/data_basic_use_guideline.html>

The source is the authenticated ODPT Tokyo Metro static feed. Developer
registration and a consumer key are required. The credential is supplied only
through `ODPT_API_TOKEN`; check that the variable exists, but never print its
value or put it in a command line, report, archive, or application bundle.
The application must retain the ODPT attribution/disclaimer and the accepted
feed version, validity period, and acquisition time. Raw authenticated source
data is not committed or redistributed.

The accepted input for this release is:

| Field | Accepted value |
| --- | --- |
| Feed version | `20261008` |
| Validity | `2026-09-19` through `2027-03-12` |
| ZIP SHA-256 | `c50ab5cc3489bf1ff67985491a4d00d25888655918ef887a6cc4887a007dfd73` |
| Station master SHA-256 | `542182aea888d559ca37433ed862248658ffb7ae08a9b7be5641b59eafd129ec` |
| Railway master SHA-256 | `90b16083b4acfd73d4ad4dc840f6702e57799279d05d1e6781961c8ab3b97f6c` |

## Update detection and staging

1. Check the official catalog/resource and applicable ODPT update notice. The
   currently documented operating requirement is to process an applicable
   update within one week; record the check time even when no update exists.
2. Confirm only the presence of `ODPT_API_TOKEN`. Do not echo or log it.
3. Download the archive and Tokyo Metro station/railway masters into a newly
   created staging directory. Never download over the accepted input or an
   active runtime artifact.
4. Calculate SHA-256 locally and record the proposed version, validity dates,
   source URL, and acquisition time. A different hash or version is a new
   input and must not inherit the old release label.
5. Run the fail-closed verifier before extraction into a build worktree:

   ```powershell
   python -X utf8 api/tokyo_metro_release_inputs.py `
     --archive C:\staging\TokyoMetro-Train-GTFS.zip `
     --stations C:\staging\odpt_Station_TokyoMetro.json `
     --railways C:\staging\odpt_Railway_TokyoMetro.json `
     --counterpart-stations C:\release-worktree\api\data\odpt_Station.json `
     --transfer-manifest C:\release-worktree\api\config\tokyo_metro_reviewed_transfers.json `
     --base-app-data C:\release-worktree\api\data\app_data.pkl `
     --expected-archive-sha256 c50ab5cc3489bf1ff67985491a4d00d25888655918ef887a6cc4887a007dfd73 `
     --expected-station-sha256 542182aea888d559ca37433ed862248658ffb7ae08a9b7be5641b59eafd129ec `
     --expected-railway-sha256 90b16083b4acfd73d4ad4dc840f6702e57799279d05d1e6781961c8ab3b97f6c `
     --expected-counterpart-stations-sha256 1b3007aaebc7a30f824f9c555913ecb15c0da9c83d389d2c5551e9c3930b0fe3 `
     --expected-transfer-manifest-sha256 abd91114dc29042c4e4491f421a21555cc1504d90a4cc4dc2ef5262fdb966c5a `
     --expected-base-app-data-sha256 db10fc598e0da81e2ac200ba742ab75283440823651fb1d800037f7c0a74bae5 `
     --expected-version 20261008 `
     --expected-valid-from 2026-09-19 `
     --expected-valid-until 2027-03-12 `
     --service-date 2026-10-23
   ```

6. Build in a disposable release worktree only after the verifier accepts all
   inputs. Run the fixed Phase 2/3 corpus and release tests against the newly
   built artifact. Do not overwrite or relabel an accepted artifact in place.
7. Publication or pointer changes are separate, explicitly approved deployment
   actions. Until every validation and approval succeeds, the current published
   artifact/pointer remains unchanged.

## Fail-closed behavior

`tokyo_metro_release_inputs.py` verifies the exact archive hash, ZIP structure
and CRC, required GTFS files, feed version and period, requested service date,
station/railway master hashes and IDs, and the complete transfer-manifest
application against the base graph. It rejects an invalid ZIP, missing member,
unsafe or duplicate member, station-ID mismatch, different feed edition, and a
date outside the effective period.

The verifier extracts only to its own temporary directory and never edits the
active input or runtime artifact. Regression tests keep a sentinel active
artifact unchanged after rejection. Therefore a failed update cannot be
published as the new version through this procedure. It is also forbidden to
silently use the old archive while recording a new version/hash.

At or after expiry, a service date outside the pinned period fails validation;
the operator must acquire and validate a new official feed. Continuing to label
the expired feed as current is not an allowed fallback.
