"""Fail-fast checks for ORM tables and columns missing from the live database."""

from dataclasses import dataclass

from sqlalchemy import inspect


@dataclass(frozen=True)
class MissingSchemaObject:
    """A model-backed table/view or column absent from the database."""

    relation: str
    column: str | None = None
    is_view: bool = False

    def label(self) -> str:
        kind = "view" if self.is_view else "table"
        if self.column:
            return f"{self.relation}.{self.column} (column)"
        return f"{self.relation} ({kind})"


def find_missing_model_schema(engine, metadata) -> list[MissingSchemaObject]:
    """Return model-backed relations/columns missing from the live schema.

    This intentionally checks only existence. Alembic autogenerate reports a
    large amount of harmless legacy type/index naming drift; missing relations
    and columns are the runtime-breaking class that causes UndefinedTable and
    UndefinedColumn errors.
    """

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    view_names = set(inspector.get_view_names())
    missing: list[MissingSchemaObject] = []

    for table in metadata.sorted_tables:
        is_view = bool(table.info.get("is_view"))
        existing_relations = view_names if is_view else table_names

        if table.name not in existing_relations:
            missing.append(MissingSchemaObject(table.name, is_view=is_view))
            continue

        database_columns = {
            column["name"] for column in inspector.get_columns(table.name)
        }
        for column in table.columns:
            if column.name not in database_columns:
                missing.append(
                    MissingSchemaObject(
                        table.name,
                        column=column.name,
                        is_view=is_view,
                    )
                )

    return missing


def assert_model_schema_matches_database(engine, metadata) -> None:
    """Raise RuntimeError when a model requires a missing relation or column."""

    missing = find_missing_model_schema(engine, metadata)
    if not missing:
        return

    details = "\n".join(f"  - {item.label()}" for item in missing)
    raise RuntimeError(
        "Database schema is missing objects required by SQLAlchemy models:\n"
        f"{details}\n"
        "Apply the pending Alembic migrations before starting the application."
    )
