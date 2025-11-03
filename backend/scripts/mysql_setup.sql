CREATE TABLE IF NOT EXISTS JOB_TABLE (
    id INT AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(255),
    job_name VARCHAR(255),
    job_run_name VARCHAR(255),
    output_s3_path TEXT,
    job_type VARCHAR(255),
    job_status VARCHAR(255),
    job_create_time DATETIME,
    job_start_time DATETIME,
    job_end_time DATETIME,
    job_payload TEXT,
    ts BIGINT,
    error_message TEXT DEFAULT NULL,
    INDEX idx_job_status (job_status),
    INDEX idx_job_id (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS EP_TABLE (
    id INT AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(255),
    endpoint_name VARCHAR(255),
    model_name VARCHAR(255),
    engine VARCHAR(16),
    enable_lora BOOLEAN,
    instance_type VARCHAR(64),
    instance_count INT,
    model_s3_path TEXT,
    endpoint_status VARCHAR(16),
    endpoint_create_time DATETIME,
    endpoint_delete_time DATETIME,
    extra_config TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS USER_TABLE (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(32),
    userpwd VARCHAR(32),
    groupname VARCHAR(32),
    extra_config TEXT

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;