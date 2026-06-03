"""Apply sql/schema.sql to the local Postgres database. Idempotent (CREATE IF NOT EXISTS)."""
from db import ROOT, local_engine


def main() -> None:
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    eng = local_engine()
    with eng.begin() as conn:
        # psycopg2 executes the whole multi-statement script in one call.
        conn.exec_driver_sql(schema)
    print("Schema applied to local DB.")


if __name__ == "__main__":
    main()
