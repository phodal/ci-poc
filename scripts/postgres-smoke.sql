\set ON_ERROR_STOP on
CREATE TABLE smoke_items (id integer PRIMARY KEY, label text NOT NULL);
BEGIN;
INSERT INTO smoke_items VALUES (1, 'committed');
COMMIT;
BEGIN;
INSERT INTO smoke_items VALUES (2, 'rolled back');
ROLLBACK;
DO $$
BEGIN
  IF (SELECT count(*) FROM smoke_items) <> 1 THEN
    RAISE EXCEPTION 'Expected exactly one committed row';
  END IF;
  IF (SELECT label FROM smoke_items WHERE id = 1) IS DISTINCT FROM 'committed' THEN
    RAISE EXCEPTION 'Committed row did not persist';
  END IF;
  IF EXISTS (SELECT FROM smoke_items WHERE id = 2) THEN
    RAISE EXCEPTION 'Rolled-back row persisted';
  END IF;
END $$;
DROP TABLE smoke_items;
SELECT 'PostgreSQL commit/rollback assertions passed' AS result;
