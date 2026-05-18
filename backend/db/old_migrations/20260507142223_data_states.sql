-- migrate:up

-- Expand data_files.state to include the transient PROCESSING claim and a
-- terminal FAILED state, both needed once Worker 1 (blob_builder) starts
-- claiming files and reporting outcomes.
ALTER TABLE data_files DROP CONSTRAINT data_files_state_check;
ALTER TABLE data_files ADD CONSTRAINT data_files_state_check
    CHECK (state IN ('PENDING', 'PROCESSING', 'READY', 'FAILED'));


-- migrate:down

ALTER TABLE data_files DROP CONSTRAINT data_files_state_check;
ALTER TABLE data_files ADD CONSTRAINT data_files_state_check
    CHECK (state IN ('PENDING', 'READY'));
