-- HyperPod EKS Cluster Table
-- Run this SQL to create the CLUSTER_TABLE for storing cluster information

CREATE TABLE IF NOT EXISTS CLUSTER_TABLE (
    cluster_id VARCHAR(64) PRIMARY KEY,
    cluster_name VARCHAR(255) NOT NULL,
    eks_cluster_name VARCHAR(255) NOT NULL,
    eks_cluster_arn VARCHAR(512),
    hyperpod_cluster_arn VARCHAR(512),
    cluster_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    vpc_id VARCHAR(64),
    subnet_ids JSON,
    instance_groups JSON,
    cluster_create_time DATETIME,
    cluster_update_time DATETIME,
    error_message TEXT,
    cluster_config JSON,
    ts BIGINT NOT NULL,
    INDEX idx_cluster_name (cluster_name),
    INDEX idx_cluster_status (cluster_status),
    INDEX idx_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add comment
ALTER TABLE CLUSTER_TABLE COMMENT = 'HyperPod EKS Cluster management table';
