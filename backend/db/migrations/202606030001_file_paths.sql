------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

-- Human-readable name for a file, captured at sync time. For GDRIVE this is
-- the full folder path of the file under the synced root (e.g.
-- "Research/2024/report.pdf"); `path` keeps holding the opaque Drive file id
-- (the sync conflict key and the download handle), so this column is purely
-- for display / API consumers and never used to locate the source.
--
-- NOT NULL DEFAULT '' so rows synced before this migration keep validating
-- and simply read back as the empty string — the sync only populates `name`
-- on freshly inserted rows (ON CONFLICT DO NOTHING), so a pre-existing file
-- stays blank until it is cleared and re-synced.
ALTER TABLE data_files ADD COLUMN name TEXT NOT NULL DEFAULT '';


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

ALTER TABLE data_files DROP COLUMN name;
