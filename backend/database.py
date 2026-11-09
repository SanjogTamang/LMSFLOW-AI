from typing import Any, Dict, List, Optional

from supabase import Client, create_client

from backend.config import settings


class SupabaseDataError(RuntimeError):
    pass


class SupabaseDatabase:
    """Service-role database adapter for server operations.

    Service-role access intentionally bypasses RLS. Every public operation
    therefore requires an explicit user_id filter for tenant-owned tables.
    This is enforced on mutation helpers to avoid accidentally leaking data.
    """

    USER_SCOPED_TABLES = {
        "profiles", "student_lms_connections", "courses", "assignments",
        "assignment_drafts", "generated_documents", "submission_jobs",
        "submission_events",
    }

    def __init__(self, url: str, service_role_key: str):
        if not url or not service_role_key:
            raise SupabaseDataError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for server database access"
            )
        self.client: Client = create_client(url, service_role_key)

    @staticmethod
    def _raise(result: Any) -> Any:
        error = getattr(result, "error", None)
        if error:
            raise SupabaseDataError(str(error))
        return result

    def select(
        self,
        table: str,
        filters: Optional[Dict[str, Any]] = None,
        columns: str = "*",
        single: bool = False,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        filters = filters or {}
        self._validate_scope(table, filters)
        query = self.client.table(table).select(columns)
        for column, value in filters.items():
            query = query.eq(column, value)
        if order_by:
            query = query.order(order_by)
        if limit:
            query = query.limit(limit)
        result = self._raise(query.execute())
        data = result.data or []
        if single:
            if len(data) > 1:
                raise SupabaseDataError(f"select on {table} returned multiple rows")
            return data[0] if data else None
        return data

    def insert(self, table: str, values: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_scope(table, values)
        result = self._raise(
            self.client.table(table).insert(values).execute()
        )
        if not result.data:
            raise SupabaseDataError(f"insert into {table} returned no row")
        return result.data[0]

    def update(
        self,
        table: str,
        filters: Dict[str, Any],
        values: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        self._validate_scope(table, filters)
        query = self.client.table(table).update(values)
        for column, value in filters.items():
            query = query.eq(column, value)
        result = self._raise(query.execute())
        return result.data or []

    def delete(self, table: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._validate_scope(table, filters)
        query = self.client.table(table).delete()
        for column, value in filters.items():
            query = query.eq(column, value)
        return self._raise(query.execute()).data or []

    def upsert(self, table: str, values: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_scope(table, values)
        result = self._raise(
            self.client.table(table).upsert(values).execute()
        )
        if not result.data:
            raise SupabaseDataError(f"upsert into {table} returned no row")
        return result.data[0]

    def _validate_scope(self, table: str, values: Dict[str, Any]) -> None:
        if table == "profiles":
            if not ({"id", "email", "scu_student_id"} & values.keys()):
                raise SupabaseDataError(
                    "profiles operations require an explicit id, email, or scu_student_id"
                )
        elif table in self.USER_SCOPED_TABLES and "user_id" not in values:
            raise SupabaseDataError(
                f"{table} operations require an explicit user_id filter"
            )


_database: Optional[SupabaseDatabase] = None


def get_database() -> SupabaseDatabase:
    global _database
    if _database is None:
        _database = SupabaseDatabase(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _database


def get_supabase_client() -> Optional[Client]:
    """Public-anon client for browser-facing Auth calls and token checks."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        return None
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
