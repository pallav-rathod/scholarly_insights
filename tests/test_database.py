import unittest

from app.db import POSTGRES_SCHEMA, PostgresConnection


class RecordingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, parameters=()):
        self.statements.append((statement, parameters))


class PostgresConnectionTests(unittest.TestCase):
    def test_execute_translates_placeholders_without_changing_parameters(self):
        connection = RecordingConnection()
        db = PostgresConnection(connection)
        parameters = ("paper-1", "A title")

        db.execute(
            "INSERT INTO articles(arxiv_id, title) VALUES (?, ?)", parameters
        )

        self.assertEqual(
            connection.statements,
            [
                (
                    "INSERT INTO articles(arxiv_id, title) VALUES (%s, %s)",
                    parameters,
                )
            ],
        )

    def test_postgres_schema_has_no_sqlite_only_statements(self):
        connection = RecordingConnection()

        PostgresConnection(connection).executescript(POSTGRES_SCHEMA)

        statements = [statement for statement, _ in connection.statements]
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS articles" in s for s in statements))
        self.assertTrue(any("ON CONFLICT (singleton_id) DO NOTHING" in s for s in statements))
        self.assertFalse(any("PRAGMA" in statement for statement in statements))
        self.assertFalse(any("INSERT OR IGNORE" in statement for statement in statements))


if __name__ == "__main__":
    unittest.main()
