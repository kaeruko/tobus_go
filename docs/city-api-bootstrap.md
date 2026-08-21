# City API production bootstrap

Phase 8 production bootstrap for the Nagoya and Sendai backends.

## Scope

The one-time bootstrap is intentionally split from normal image deployment.

1. `infra/city-api-base.yaml` creates only the city-owned base resources:
   - private, versioned S3 bucket for validated GTFS bundles;
   - immutable ECR repository (`nagoyago-api` or `sendaigo-api`);
   - Lambda execution role with read access limited to that city's GTFS prefix;
   - retained CloudWatch Logs log group.
2. `scripts/bootstrap_city_api.ps1` validates an already-approved local GTFS directory, packages and uploads that exact bundle, pushes the first Lambda image, creates the city Lambda and public Function URL, and runs the strict preflight.
3. Later code-only releases use `scripts/deploy_api.ps1`; the bootstrap script refuses to mutate an existing Lambda.

Tokyo resources are never used as fallback by this flow.

## Required local inputs

- AWS CLI authenticated to the intended account and region.
- Docker.
- Ignored local `api/.env` containing exactly one non-empty, unquoted `GOOGLE_MAPS_API_KEY`.
- An already validated city GTFS directory produced by the repository fetch/validation flow. The directory must contain the city manifest plus the required GTFS files.
- The exact approved revision/service date passed as `-ExpectedDataVersion`.

Do not paste secrets into command arguments, issue comments, or chat. The bootstrap reads the Google key locally and writes it only to a temporary environment JSON file that is deleted in `finally`.

## Nagoya example

```powershell
.\scripts\bootstrap_city_api.ps1 `
  -City nagoya `
  -GtfsDir C:\path\to\validated\nagoya `
  -ExpectedDataVersion 2026-03-28
```

For Nagoya, `ExpectedDataVersion` must exactly match `revision` in `nagoya_gtfs_manifest.json`.

## Sendai example

```powershell
.\scripts\bootstrap_city_api.ps1 `
  -City sendai `
  -GtfsDir C:\path\to\validated\sendai `
  -ExpectedDataVersion 2026-08-22
```

For Sendai, `ExpectedDataVersion` must exactly match `validated_service_date` in `sendai_gtfs_manifest.json` and be within the manifest coverage.

## Function URL permission model

New Lambda Function URLs require both `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` permission for public `NONE` auth. The second permission is restricted with `InvokedViaFunctionUrl=true`. `inspect_city_infra.ps1` verifies both exact statements.

## Failure behavior

The bootstrap does not search another region, resource name, bucket, GTFS source, or Tokyo resource. Existing Lambda detection, data/version mismatch, missing secret, unsupported image manifest, or AWS errors stop the bootstrap with diagnostics. It does not silently replace the approved GTFS input.
