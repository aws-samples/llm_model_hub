-- Add error_message field to JOB_TABLE
-- This field will store detailed error messages when a job fails
SET @col_exists = (
    SELECT COUNT(*) 
    FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = DATABASE() 
    AND TABLE_NAME = 'JOB_TABLE' 
    AND COLUMN_NAME = 'error_message'
);
SET @query = IF(@col_exists = 0, 
    'ALTER TABLE JOB_TABLE ADD COLUMN error_message TEXT DEFAULT NULL', 
    'SELECT "Column already exists" AS message'
);
PREPARE stmt FROM @query;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;