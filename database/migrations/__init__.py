"""database/migrations — explicit, one-off schema migrations.

Brain Bot has never needed a formal migration framework before (see
journal/journal_v2.py's own comment about deliberately avoiding ALTER
TABLE by using a JSON blob instead). This package exists because W14-2D-1
is the first change that must retrofit a NOT NULL + CHECK column onto
tables that may already hold historical rows in an operator's live
database file — something CREATE TABLE IF NOT EXISTS cannot do.

Each migration module is a standalone, idempotent script: safe to run
zero, one, or many times against the same database file. Nothing in
database/db.py invokes these automatically — an operator (or a bundled
startup check) runs them explicitly, once, against their real database
file, before relying on the new column.
"""
