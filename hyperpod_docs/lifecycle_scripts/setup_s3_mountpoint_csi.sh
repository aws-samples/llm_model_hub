#!/bin/bash
# =============================================================================
# HyperPod EKS - Mountpoint for Amazon S3 CSI Driver Setup
# =============================================================================
# This script installs and configures the Mountpoint for Amazon S3 CSI driver
# on an Amazon EKS cluster for use with SageMaker HyperPod.
#
# Reference:
# - https://docs.aws.amazon.com/eks/latest/userguide/s3-csi.html
# - https://catalog.workshops.aws/sagemaker-hyperpod-eks/en-US/01-cluster/09-s3-mountpoint
#
# Prerequisites:
# - kubectl configured with cluster access
# - AWS CLI configured
# - eksctl installed
# - IAM OIDC provider associated with the cluster
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# =============================================================================
# Configuration
# =============================================================================

# Required environment variables
: "${EKS_CLUSTER_NAME:?'EKS_CLUSTER_NAME environment variable is required'}"
: "${AWS_REGION:?'AWS_REGION environment variable is required'}"
: "${S3_BUCKET_NAME:?'S3_BUCKET_NAME environment variable is required'}"

# Optional configuration
ROLE_NAME="${S3_CSI_ROLE_NAME:-AmazonEKS_S3_CSI_DriverRole-${EKS_CLUSTER_NAME}}"
POLICY_NAME="${S3_CSI_POLICY_NAME:-AmazonS3CSIDriverPolicy-${EKS_CLUSTER_NAME}}"
NAMESPACE="${S3_CSI_NAMESPACE:-kube-system}"
SERVICE_ACCOUNT_NAME="${S3_CSI_SA_NAME:-s3-csi-driver-sa}"

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)

log_info "==================================================================="
log_info "Mountpoint for Amazon S3 CSI Driver Setup"
log_info "==================================================================="
log_info "EKS Cluster: $EKS_CLUSTER_NAME"
log_info "Region: $AWS_REGION"
log_info "S3 Bucket: $S3_BUCKET_NAME"
log_info "Account ID: $ACCOUNT_ID"
log_info "==================================================================="

# =============================================================================
# Step 1: Create IAM Policy
# =============================================================================
create_iam_policy() {
    log_info "[Step 1/4] Creating IAM policy for S3 access..."

    # Check if policy already exists
    if aws iam get-policy --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}" &>/dev/null; then
        log_warn "IAM policy ${POLICY_NAME} already exists, skipping creation"
        return 0
    fi

    # Create policy document
    cat > /tmp/s3-csi-policy.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "MountpointFullBucketAccess",
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::${S3_BUCKET_NAME}"
            ]
        },
        {
            "Sid": "MountpointFullObjectAccess",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:AbortMultipartUpload",
                "s3:DeleteObject"
            ],
            "Resource": [
                "arn:aws:s3:::${S3_BUCKET_NAME}/*"
            ]
        }
    ]
}
EOF

    aws iam create-policy \
        --policy-name "${POLICY_NAME}" \
        --policy-document file:///tmp/s3-csi-policy.json \
        --description "IAM policy for Mountpoint S3 CSI driver access to ${S3_BUCKET_NAME}"

    log_info "IAM policy created: arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
}

# =============================================================================
# Step 2: Create IAM Role with IRSA
# =============================================================================
create_iam_role() {
    log_info "[Step 2/4] Creating IAM role with IRSA..."

    # Check if OIDC provider exists
    OIDC_ID=$(aws eks describe-cluster --name "${EKS_CLUSTER_NAME}" \
        --query "cluster.identity.oidc.issuer" --output text | cut -d '/' -f 5)

    if [[ -z "$OIDC_ID" ]]; then
        log_error "OIDC provider not found. Please run: eksctl utils associate-iam-oidc-provider --cluster ${EKS_CLUSTER_NAME} --approve"
        exit 1
    fi

    log_info "OIDC Provider ID: $OIDC_ID"

    # Create IAM service account using eksctl
    POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"

    eksctl create iamserviceaccount \
        --name "${SERVICE_ACCOUNT_NAME}" \
        --namespace "${NAMESPACE}" \
        --cluster "${EKS_CLUSTER_NAME}" \
        --attach-policy-arn "${POLICY_ARN}" \
        --approve \
        --role-name "${ROLE_NAME}" \
        --region "${AWS_REGION}" \
        --override-existing-serviceaccounts || true

    log_info "IAM role created: ${ROLE_NAME}"
}

# =============================================================================
# Step 3: Install S3 CSI Driver Add-on
# =============================================================================
install_csi_driver() {
    log_info "[Step 3/4] Installing Mountpoint for Amazon S3 CSI driver..."

    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

    # Check if add-on already exists
    if aws eks describe-addon --cluster-name "${EKS_CLUSTER_NAME}" --addon-name aws-mountpoint-s3-csi-driver &>/dev/null; then
        log_warn "S3 CSI driver add-on already installed, updating..."
        aws eks update-addon \
            --cluster-name "${EKS_CLUSTER_NAME}" \
            --addon-name aws-mountpoint-s3-csi-driver \
            --service-account-role-arn "${ROLE_ARN}" \
            --resolve-conflicts OVERWRITE \
            --region "${AWS_REGION}"
    else
        aws eks create-addon \
            --cluster-name "${EKS_CLUSTER_NAME}" \
            --addon-name aws-mountpoint-s3-csi-driver \
            --service-account-role-arn "${ROLE_ARN}" \
            --resolve-conflicts OVERWRITE \
            --region "${AWS_REGION}"
    fi

    # Wait for add-on to be active
    log_info "Waiting for S3 CSI driver add-on to be active..."
    aws eks wait addon-active \
        --cluster-name "${EKS_CLUSTER_NAME}" \
        --addon-name aws-mountpoint-s3-csi-driver \
        --region "${AWS_REGION}"

    log_info "S3 CSI driver add-on installed successfully"
}

# =============================================================================
# Step 4: Create PersistentVolume and PersistentVolumeClaim
# =============================================================================
create_storage_resources() {
    log_info "[Step 4/4] Creating PersistentVolume and PersistentVolumeClaim..."

    # Create PersistentVolume
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: s3-pv-${S3_BUCKET_NAME}
spec:
  capacity:
    storage: 1200Gi  # Ignored by S3, but required by Kubernetes
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  claimRef:
    namespace: default
    name: s3-pvc
  csi:
    driver: s3.csi.aws.com
    volumeHandle: s3-csi-driver-volume-${S3_BUCKET_NAME}
    volumeAttributes:
      bucketName: ${S3_BUCKET_NAME}
EOF

    # Create PersistentVolumeClaim
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: s3-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ""
  resources:
    requests:
      storage: 1200Gi  # Ignored by S3, but required by Kubernetes
  volumeName: s3-pv-${S3_BUCKET_NAME}
EOF

    log_info "PersistentVolume and PersistentVolumeClaim created"
}

# =============================================================================
# Main Execution
# =============================================================================

main() {
    # Associate OIDC provider if not exists
    log_info "Checking OIDC provider..."
    eksctl utils associate-iam-oidc-provider \
        --region="${AWS_REGION}" \
        --cluster="${EKS_CLUSTER_NAME}" \
        --approve 2>/dev/null || true

    create_iam_policy
    create_iam_role
    install_csi_driver
    create_storage_resources

    log_info "==================================================================="
    log_info "Mountpoint for Amazon S3 CSI Driver Setup Complete!"
    log_info "==================================================================="
    log_info ""
    log_info "To use S3 storage in your pods, add the following volume mount:"
    log_info ""
    log_info "  volumes:"
    log_info "    - name: s3-storage"
    log_info "      persistentVolumeClaim:"
    log_info "        claimName: s3-pvc"
    log_info "  containers:"
    log_info "    - volumeMounts:"
    log_info "        - name: s3-storage"
    log_info "          mountPath: /mnt/s3"
    log_info ""
    log_info "==================================================================="
}

# Run main function
main "$@"
