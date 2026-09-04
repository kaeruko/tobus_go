#!/usr/bin/env bash
set -euo pipefail

REGION="us-west-2"
ACCOUNT_ID="667674573054"
ECR_REPO="toeigo-api"
LAMBDA_NAME="toeigo-api"

AWS="aws.exe"
DOCKER="docker.exe"

TAG="${1:-$(date +%Y%m%d-%H%M)}"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${ECR_REPO}:${TAG}"

echo "======================================"
echo "Deploy ToBus API"
echo "IMAGE: ${IMAGE}"
echo "======================================"

# --------------------------------------------------
# 0. 実行環境チェック
# --------------------------------------------------

if [[ ! -f "Dockerfile" ]]; then
  echo "ERROR: Dockerfile がありません。" >&2
  echo "api/ ディレクトリから実行してください。" >&2
  exit 1
fi

if ! command -v "${AWS}" >/dev/null 2>&1; then
  echo "ERROR: aws.exe がWSLから見つかりません。" >&2
  echo "確認コマンド: aws.exe --version" >&2
  exit 1
fi

if ! command -v "${DOCKER}" >/dev/null 2>&1; then
  echo "ERROR: docker.exe がWSLから見つかりません。" >&2
  echo "Docker Desktopが起動しているか確認してください。" >&2
  echo "確認コマンド: docker.exe --version" >&2
  exit 1
fi

echo
echo "[0/6] Environment check"

"${AWS}" --version
"${DOCKER}" --version

CURRENT_ACCOUNT="$(
  "${AWS}" sts get-caller-identity \
    --query Account \
    --output text |
  tr -d '\r'
)"

if [[ "${CURRENT_ACCOUNT}" != "${ACCOUNT_ID}" ]]; then
  echo "ERROR: AWSアカウントが違います。" >&2
  echo "expected: ${ACCOUNT_ID}" >&2
  echo "actual:   ${CURRENT_ACCOUNT}" >&2
  exit 1
fi

echo "AWS account: ${CURRENT_ACCOUNT}"

# --------------------------------------------------
# 1. ECR login
# --------------------------------------------------

echo
echo "[1/6] ECR login"

"${AWS}" ecr get-login-password \
  --region "${REGION}" |
"${DOCKER}" login \
  --username AWS \
  --password-stdin "${REGISTRY}"

# --------------------------------------------------
# 2. Docker build
# --------------------------------------------------

echo
echo "[2/6] Docker build"

"${DOCKER}" buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --load \
  -t "${IMAGE}" \
  .

# --------------------------------------------------
# 3. Docker push
# --------------------------------------------------

echo
echo "[3/6] Docker push"

"${DOCKER}" push "${IMAGE}"

# --------------------------------------------------
# 4. ECR manifest確認
# --------------------------------------------------

echo
echo "[4/6] Check ECR manifest"

MEDIA_TYPE="$(
  "${AWS}" ecr batch-get-image \
    --repository-name "${ECR_REPO}" \
    --image-ids imageTag="${TAG}" \
    --region "${REGION}" \
    --query 'images[0].imageManifestMediaType' \
    --output text |
  tr -d '\r'
)"

echo "manifest: ${MEDIA_TYPE}"

case "${MEDIA_TYPE}" in
  application/vnd.docker.distribution.manifest.v2+json)
    ;;
  application/vnd.oci.image.manifest.v1+json)
    ;;
  *)
    echo "ERROR: Lambdaで使わないmanifest形式です。" >&2
    echo "manifest: ${MEDIA_TYPE}" >&2
    exit 1
    ;;
esac

# --------------------------------------------------
# 5. Lambda更新
# --------------------------------------------------

echo
echo "[5/6] Update Lambda"

"${AWS}" lambda update-function-code \
  --function-name "${LAMBDA_NAME}" \
  --image-uri "${IMAGE}" \
  --region "${REGION}"

echo
echo "Waiting for Lambda update..."

"${AWS}" lambda wait function-updated \
  --function-name "${LAMBDA_NAME}" \
  --region "${REGION}"

# --------------------------------------------------
# 6. 実際にLambdaへ入ったImageUriを確認
# --------------------------------------------------

echo
echo "[6/6] Verify deployed image"

DEPLOYED_IMAGE="$(
  "${AWS}" lambda get-function \
    --function-name "${LAMBDA_NAME}" \
    --region "${REGION}" \
    --query 'Code.ImageUri' \
    --output text |
  tr -d '\r'
)"

echo "expected: ${IMAGE}"
echo "actual:   ${DEPLOYED_IMAGE}"

if [[ "${DEPLOYED_IMAGE}" != "${IMAGE}" ]]; then
  echo "ERROR: LambdaのImageUriが一致しません。" >&2
  exit 1
fi

echo
echo "======================================"
echo "DEPLOY SUCCESS"
echo "${IMAGE}"
echo "======================================"
