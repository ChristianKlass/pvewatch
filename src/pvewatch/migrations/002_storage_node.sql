-- Add node column to storage_snapshots for multi-node cluster support
ALTER TABLE storage_snapshots ADD COLUMN node TEXT NOT NULL DEFAULT '';
