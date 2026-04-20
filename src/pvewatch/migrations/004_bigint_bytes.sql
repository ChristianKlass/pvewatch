ALTER TABLE storage_snapshots ALTER COLUMN total_bytes TYPE BIGINT;
ALTER TABLE storage_snapshots ALTER COLUMN used_bytes TYPE BIGINT;
ALTER TABLE backup_results ALTER COLUMN size_bytes TYPE BIGINT;
