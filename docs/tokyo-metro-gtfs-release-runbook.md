# Tokyo Metro static GTFS release runbook

Use this procedure to verify the accepted Tokyo Metro inputs and release a
content-addressed Tokyo API graph from `main`.

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
| Transfer policy | `tokyo_metro_transfer_policy/v3` |
| Transfer manifest SHA-256 | `c0dae240d9617f7101f3cf92323b82696200977128dbf7328878c13dc98ce729` |

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
5. Run the fail-closed verifier from the release checkout on `main`. The
   example uses the pinned October Toei-only base to validate Metro inputs.
   The November transfer-only rebuild uses the separately pinned production
   graph described below.

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
     --expected-transfer-manifest-sha256 c0dae240d9617f7101f3cf92323b82696200977128dbf7328878c13dc98ce729 `
     --expected-base-app-data-sha256 db10fc598e0da81e2ac200ba742ab75283440823651fb1d800037f7c0a74bae5 `
     --expected-version 20261008 `
     --expected-valid-from 2026-09-19 `
     --expected-valid-until 2027-03-12 `
     --service-date 2026-11-25
   ```

6. Write the staged build to a separate `app_data.pkl` after input verification.
   For a full `api/prebuild.py` build, set `PREBUILT_OUTPUT` to the staging
   path and validate the Toei source hashes against their release manifest.
   For a transfer-only rebuild, regenerate the Metro portion from the accepted
   inputs against the verified production base and compare the non-transfer
   edges, timetables and spatial index before release.
7. Run the API regression suite and the fixed route corpus against the staged
   graph. Pass the verified v3 manifest to the corpus reviewer with
   `--transfer-manifest`. Use a date inside the pinned bus feed's validity for
   bus-scoped cases and keep the historical Metro cases, including the holiday
   and last-train probes. Compare ordered Toei-only results against the
   production base with the same feed and dates.
8. Publish the verified graph to `deployments/prebuilt/<sha256>/app_data.pkl`
   using an S3 create-only write and a SHA-256 checksum. Download the object
   again and verify its bytes. Record the live Lambda revision, resolved image
   digest, S3 graph key and configuration before cutover. Keep secrets out of
   release records and preserve the entire environment map when changing its
   graph key.
9. Validate startup and route searches for the image/graph combinations used
   during cutover and use Lambda revision guards for both configuration and
   image updates. `scripts/deploy_api.ps1` updates the image only. Verify that
   Lambda points to the approved graph before updating the image. Confirm
   `/healthz` and actual `POST /route` results after the cutover.

## November 25, 2026 v3 release

- Graph source commit: `00b80fe2a7371aca937e19339e1cf8954c20cb45`.
- Published graph: `s3://toeigo-314267685786/deployments/prebuilt/074952198fe859eb32e8c455a2eaf54ae687a291fea14f2d78a59d47a86c8f86/app_data.pkl`.
- Previous graph: `s3://toeigo-314267685786/deployments/prebuilt/1244e23a286e088e422bc26e6eb8716bd995277f799ad2d4d690042e76f55c8b/app_data.pkl`.
- Lambda source commit: `86897e9852b07669a44df848ab1a3a3789374158`.
- Deployed ECR image: `toeigo-api:20261125T004628Z`, digest `sha256:06f38680c43bb64fdd068428d2e8cf1765f0d3dad36efdf079cd76fa07bc010e`.
- Rollback image: `sha256:5ba2795462ba885cf4a5a6595b6958efc5af09742c6c36302d9c8729b45e7e4f`.
  Both images passed startup and route checks with the published v3 graph.
  Reverting the graph separately requires the previous S3 key and an
  environment update based on the complete current variable map.
- Toei Bus GTFS: `20261122_030832`, SHA-256 `5323838039242bcb660457bab9217fe4460b0a128584a1e0bfccf3112cf7bff5`.
- ODPT `connectingStation` backed 117 coordinate-based pairs and four
  reviewed pairs. All 242 directed transfer edges were checked, and 66,328
  non-transfer edges matched the previous graph.
- API regression suite passed 860 tests. The release corpus passed 188
  searches, including 60 Toei-only results identical to the previous graph.
  The independent review checked 462 Metro rides against GTFS.
- The public API reported ready and returned a 243 m, 4 min coordinate-based
  transfer at Otemachi for Nakano-sakaue to Myoden in ordinary search.
  Shin-egota to Myoden used the official Toei Shinjuku to Metro Tozai
  connection at Kudanshita with a 74 m, 1 min transfer.
  The reviewed Ningyocho to Suitengumae transfer stayed at 150 m and 7 min.
- GitHub Actions verified the published graph with the recorded graph source
  and object hash. [Successful dry run](https://github.com/kaeruko/tobus_go/actions/runs/45519903669).

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
