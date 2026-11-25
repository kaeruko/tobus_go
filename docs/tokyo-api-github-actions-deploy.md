# Tokyo API GitHub Actions deploy

The [Tokyo API workflow](../.github/workflows/tokyo_api_deploy.yml) deploys the Tokyo backend to the `toeigo-api` ECR repository and Lambda in AWS `us-west-2`, account `314267685786`.

## Activation — owner action required

Nothing auto-deploys until the owner has explicitly completed these steps.

1. In GitHub, create the `tokyo-api-production` environment, restrict it to the `main` branch, and optionally require human approval. Configure AWS IAM OIDC federation for `token.actions.githubusercontent.com` with audience `sts.amazonaws.com`. The deployment role must use this exact trust-condition subject: `repo:kaeruko/tobus_go:environment:tokyo-api-production`. Do not use long-lived AWS access keys.
2. Grant the role *only* the permissions needed to describe/push ECR images in `toeigo-api`, read/update the `toeigo-api` Lambda, and `s3:GetObject` for the exact active prebuilt graph object. `ecr:GetAuthorizationToken` must be scoped to `*` as required by ECR. There must be no S3 write, IAM modification, Lambda configuration update, or arbitrary Lambda resource access.
3. Set the following **GitHub repository variables** under Settings → Secrets and variables → Actions → Variables:
   - `TOKYO_API_DEPLOY_ROLE_ARN` — the assumed-role ARN (not an AWS access key).
   - `TOKYO_API_DATA_BASELINE_SHA` — the 40-character **Git commit that actually produced the S3 prebuilt graph**. Never advance this variable unless the S3 prebuilt has been rebuilt, reviewed, and published from that source.
   - `TOKYO_API_PREBUILT_SHA256` — the SHA-256 of the **actual approved S3 prebuilt pickle**, not of a similarly named local file.
   - `TOKYO_API_HEALTH_URL` — the existing production HTTPS endpoint **ending in `/healthz`**.
   - `TOKYO_API_AUTO_DEPLOY` — leave unset or `false` while testing; set to the literal `true` only after a successful dry run, a verified production deployment, and confirmation that the role/environment are restricted correctly.
4. The Tokyo Lambda must explicitly set `S3_BUCKET_NAME` and `S3_PREBUILT_KEY` to the approved prebuilt object. The workflow refuses to guess the key when the environment variable is absent, even if application code has a legacy default. Its architecture must be `x86_64`, package type `Image`, and `APP_CITY` either absent or `tokyo` (same existing Tokyo guard).
5. In GitHub Actions, run **Tokyo API deploy → Run workflow → dry_run=true** on `main`. This runs the API tests, authenticates with OIDC, checks the live AWS target and S3 prebuilt SHA-256, and builds/inspects the Docker image **without touching ECR or Lambda**.
6. Only when ready, run once with `dry_run=false`. It pushes an image under a unique source/run/attempt tag and verifies the ECR manifest. The Lambda update uses the image digest and the revision captured when the S3 configuration was verified, so a concurrent Lambda configuration change stops the release. The job waits for Lambda, verifies the resolved digest, and checks the public `/healthz` response.
7. After that, setting `TOKYO_API_AUTO_DEPLOY=true` triggers the same deployment job when the existing `CI` workflow finishes **successfully on a push to main**. PR builds, failed CI, old main commits, unrelated repositories, and other branches cannot auto-deploy. Jobs are serialized and are never auto-cancelled during production mutation.

## Critical graph/data safety gate

`api/Dockerfile` does **not** bundle the Python pickle or authenticated Metro GTFS. The deployed Lambda reads the graph from S3. Therefore changing graph-building code **does not update the deployed graph on its own**.

The workflow compares the approved `TOKYO_API_DATA_BASELINE_SHA` to the target source commit. If a graph-sensitive file such as `api/tokyo_metro_gtfs.py`, `api/tokyo_metro_transfer_model.py`, `api/config/tokyo_metro_reviewed_transfers.json`, or `api/toei_engine.py` has changed, it **stops before AWS mutation**. Rebuild the data using the separately accepted ODPT source, verify the GTFS, and publish the approved S3 artifact through the manual release process. Update the deploy role's `s3:GetObject` resource to the new key and set both data variables to match that release.

**For the Metro transfer change in commits `dcb46fdd840fed427edd27375175dd8c282a5d1f` / `d5e0f6b780f1a1c9b068eff11a977eac73bc8fec`, do not set the new baseline to those commits unless the S3 graph was actually rebuilt from their code.** A code-only release against a stale S3 pickle would retain the old transfer edges.

Historical v1/v2 Metro transfer metadata and old Flutter UI translation files may remain in source. The new committed transfer manifest is checked *inside the built image* against the exact geometric v3 schema.

## Failure policy

All missing configuration, mismatched AWS account/city, wrong architecture, unverified S3 file, changed graph source, outdated main, unsuccessful tests, unsupported Docker manifest, incorrect Lambda digest, or unhealthy HTTP response **fail the job**. There are no implicit parameter substitutions or automatic alternate deployment methods. A failure after the Lambda update is reported; **there is no silent rollback**. Inspect the Action logs and deploy a new, specifically reviewed image if recovery is required.

A successful Docker push/update/health check alone does not prove Metro routes are correct in the live app. Test representative real journeys against the published dataset before enabling unattended updates.
