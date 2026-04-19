-- Add node column to vm_states for per-node VM filtering in the dashboard
ALTER TABLE vm_states ADD COLUMN node TEXT NOT NULL DEFAULT '';
