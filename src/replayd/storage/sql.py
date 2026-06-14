"""SQLAlchemy async storage implementation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sqlite3
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from replayd.models import (
    Exchange,
    Membership,
    Organization,
    Project,
    ProjectIngestKey,
    RegressionTest,
    RunSummary,
    StepDiff,
    TestResult,
    User,
)
from replayd.storage.base import Storage
from replayd.storage.blob_store import BlobStore
from replayd.storage.blobs import FilesystemBlobStore
from replayd.migrations.runner import ensure_schema
from replayd.storage.schema import (
    ExchangeRow,
    MembershipRow,
    OrganizationRow,
    ProjectIngestKeyRow,
    ProjectRow,
    RegressionTestRow,
    TestResultRow,
    UserRow,
)
from replayd.tenancy import DEFAULT_PROJECT_ID

_INIT_MAX_ATTEMPTS = 10
_INIT_RETRY_DELAY_SECONDS = 0.5


def _is_sqlite_locked_error(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        message = str(exc).lower()
        return "database is locked" in message or "locked" in message
    message = str(exc).lower()
    return "database is locked" in message or "locked" in message


def _is_sqlite_init_retryable(exc: BaseException) -> bool:
    if _is_sqlite_locked_error(exc):
        return True
    message = str(exc).lower()
    return "already exists" in message


def _is_sqlite_url(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _apply_project_ids_filter(
    stmt,
    column,
    project_ids: Sequence[str] | None,
):
    if project_ids is None:
        return stmt
    if len(project_ids) == 0:
        return stmt.where(column.in_(()))
    return stmt.where(column.in_(project_ids))


def _configure_sqlite_connection(dbapi_connection: sqlite3.Connection) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout = 5000")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def _register_sqlite_listeners(sync_engine: Engine) -> None:
    from sqlalchemy import event

    @event.listens_for(sync_engine, "connect")
    def _on_connect(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        if isinstance(dbapi_connection, sqlite3.Connection):
            _configure_sqlite_connection(dbapi_connection)


def _register_postgres_search_path(sync_engine: Engine, schema: str) -> None:
    from sqlalchemy import event

    @event.listens_for(sync_engine, "connect")
    def _on_connect(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()


class SqlStorage(Storage):
    def __init__(
        self,
        *,
        database_url: str,
        storage_dir: str,
        run_migrations_on_startup: bool = True,
        postgres_search_path: str | None = None,
        blob_store: BlobStore | None = None,
    ) -> None:
        self._database_url = database_url
        self._storage_dir = storage_dir
        self._run_migrations_on_startup = run_migrations_on_startup
        self._postgres_search_path = postgres_search_path
        self._blobs = (
            blob_store
            if blob_store is not None
            else FilesystemBlobStore(storage_dir)
        )
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def _is_sqlite(self) -> bool:
        return _is_sqlite_url(self._database_url)

    async def init(self) -> None:
        await self._blobs.init()

        last_error: Exception | None = None
        for attempt in range(_INIT_MAX_ATTEMPTS):
            try:
                await self._open_and_initialize()
                return
            except Exception as exc:
                await self._dispose_engine()
                if not self._is_sqlite or not _is_sqlite_init_retryable(exc):
                    raise
                last_error = exc
                if attempt < _INIT_MAX_ATTEMPTS - 1:
                    await asyncio.sleep(_INIT_RETRY_DELAY_SECONDS)

        raise RuntimeError(
            "Failed to initialize SQLite storage after "
            f"{_INIT_MAX_ATTEMPTS} attempts because the database remained locked"
        ) from last_error

    async def _open_and_initialize(self) -> None:
        engine = create_async_engine(self._database_url)
        if self._is_sqlite:
            _register_sqlite_listeners(engine.sync_engine)
            await self._ensure_sqlite_wal_mode(engine)
        elif self._postgres_search_path is not None:
            _register_postgres_search_path(
                engine.sync_engine,
                self._postgres_search_path,
            )

        await ensure_schema(
            engine,
            self._database_url,
            run_migrations_on_startup=self._run_migrations_on_startup,
        )

        self._engine = engine
        self._session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def _ensure_sqlite_wal_mode(self, engine: AsyncEngine) -> None:
        async with engine.connect() as conn:
            result = await conn.execute(text("PRAGMA journal_mode"))
            row = result.fetchone()
            current_mode = (row[0] if row else "").lower()
            if current_mode != "wal":
                await conn.execute(text("PRAGMA journal_mode = WAL"))
            await conn.commit()

    async def _dispose_engine(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    async def aclose(self) -> None:
        await self._dispose_engine()
        await self._blobs.aclose()

    def _require_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("SqlStorage.init() must be called before use")
        return self._session_factory

    async def put_blob(self, data: bytes) -> str:
        return await self._blobs.put_blob(data)

    async def get_blob(self, digest: str) -> bytes:
        return await self._blobs.get_blob(digest)

    async def save_exchange(self, exchange: Exchange) -> None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            session.add(_exchange_to_row(exchange))
            await session.commit()

    async def get_exchange(self, exchange_id: str) -> Exchange | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(ExchangeRow, exchange_id)
            if row is None:
                return None
            return _row_to_exchange(row)

    async def list_exchanges(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        project_ids: Sequence[str] | None = None,
    ) -> list[Exchange]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            stmt = select(ExchangeRow).order_by(
                ExchangeRow.created_at.desc(),
                ExchangeRow.id.desc(),
            )
            stmt = _apply_project_ids_filter(stmt, ExchangeRow.project_id, project_ids)
            result = await session.execute(stmt.limit(limit).offset(offset))
            return [_row_to_exchange(row) for row in result.scalars().all()]

    async def count_exchanges(self, *, project_ids: Sequence[str] | None = None) -> int:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            stmt = select(func.count()).select_from(ExchangeRow)
            stmt = _apply_project_ids_filter(stmt, ExchangeRow.project_id, project_ids)
            result = await session.execute(stmt)
            return int(result.scalar_one())

    async def list_runs(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        project_ids: Sequence[str] | None = None,
    ) -> list[RunSummary]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            grouped_stmt = select(
                ExchangeRow.run_id,
                func.count().label("step_count"),
                func.min(ExchangeRow.started_at).label("started_at"),
                func.max(ExchangeRow.ended_at).label("ended_at"),
                func.sum(ExchangeRow.latency_ms).label("total_latency_ms"),
                func.min(ExchangeRow.created_at).label("created_at"),
            ).group_by(ExchangeRow.run_id)
            grouped_stmt = _apply_project_ids_filter(
                grouped_stmt,
                ExchangeRow.project_id,
                project_ids,
            )
            grouped = await session.execute(
                grouped_stmt.order_by(
                    func.min(ExchangeRow.started_at).desc(),
                    ExchangeRow.run_id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
            summaries: list[RunSummary] = []
            for row in grouped.all():
                run_id = row.run_id
                models_stmt = (
                    select(ExchangeRow.model)
                    .where(
                        ExchangeRow.run_id == run_id,
                        ExchangeRow.model.is_not(None),
                    )
                    .distinct()
                    .order_by(ExchangeRow.model.asc())
                )
                models_stmt = _apply_project_ids_filter(
                    models_stmt,
                    ExchangeRow.project_id,
                    project_ids,
                )
                models_result = await session.execute(models_stmt)
                models = [model_row[0] for model_row in models_result.all()]
                status_stmt = (
                    select(ExchangeRow.response_status)
                    .where(ExchangeRow.run_id == run_id)
                    .order_by(
                        ExchangeRow.started_at.desc(),
                        ExchangeRow.created_at.desc(),
                        ExchangeRow.id.desc(),
                    )
                    .limit(1)
                )
                status_stmt = _apply_project_ids_filter(
                    status_stmt,
                    ExchangeRow.project_id,
                    project_ids,
                )
                status_result = await session.execute(status_stmt)
                status_row = status_result.first()
                final_status = int(status_row[0]) if status_row is not None else 0
                parent_stmt = (
                    select(ExchangeRow.parent_run_id)
                    .where(ExchangeRow.run_id == run_id)
                    .distinct()
                )
                parent_stmt = _apply_project_ids_filter(
                    parent_stmt,
                    ExchangeRow.project_id,
                    project_ids,
                )
                parent_result = await session.execute(parent_stmt)
                parent_values = [parent_row[0] for parent_row in parent_result.all()]
                parent_run_id = parent_values[0] if len(parent_values) == 1 else None
                summaries.append(
                    RunSummary(
                        run_id=run_id,
                        step_count=row.step_count,
                        started_at=datetime.fromisoformat(row.started_at),
                        ended_at=datetime.fromisoformat(row.ended_at),
                        total_latency_ms=row.total_latency_ms,
                        models=models,
                        final_status=final_status,
                        created_at=datetime.fromisoformat(row.created_at),
                        parent_run_id=parent_run_id,
                    )
                )
            return summaries

    async def count_runs(self, *, project_ids: Sequence[str] | None = None) -> int:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            stmt = select(func.count(func.distinct(ExchangeRow.run_id))).select_from(
                ExchangeRow
            )
            stmt = _apply_project_ids_filter(stmt, ExchangeRow.project_id, project_ids)
            result = await session.execute(stmt)
            return int(result.scalar_one())

    async def get_run(self, run_id: str) -> list[Exchange]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(ExchangeRow)
                .where(ExchangeRow.run_id == run_id)
                .order_by(
                    ExchangeRow.started_at.asc(),
                    ExchangeRow.created_at.asc(),
                    ExchangeRow.id.asc(),
                )
            )
            return [_row_to_exchange(row) for row in result.scalars().all()]

    async def save_test(self, test: RegressionTest) -> None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            session.add(_regression_test_to_row(test))
            await session.commit()

    async def get_test(self, test_id: str) -> RegressionTest | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(RegressionTestRow, test_id)
            if row is None:
                return None
            return _row_to_regression_test(row)

    async def list_tests(
        self,
        *,
        project_ids: Sequence[str] | None = None,
    ) -> list[RegressionTest]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            stmt = select(RegressionTestRow).order_by(
                RegressionTestRow.created_at.desc(),
                RegressionTestRow.id.desc(),
            )
            stmt = _apply_project_ids_filter(
                stmt,
                RegressionTestRow.project_id,
                project_ids,
            )
            result = await session.execute(stmt)
            return [_row_to_regression_test(row) for row in result.scalars().all()]

    async def delete_test(self, test_id: str) -> bool:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            await session.execute(
                delete(TestResultRow).where(TestResultRow.test_id == test_id)
            )
            result = await session.execute(
                delete(RegressionTestRow).where(RegressionTestRow.id == test_id)
            )
            await session.commit()
            return result.rowcount > 0

    async def save_test_result(self, result: TestResult) -> None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            session.add(_test_result_to_row(result))
            await session.commit()

    async def list_test_results(
        self,
        test_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TestResult]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            rows = await session.execute(
                select(TestResultRow)
                .where(TestResultRow.test_id == test_id)
                .order_by(TestResultRow.run_at.desc(), TestResultRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return [_row_to_test_result(row) for row in rows.scalars().all()]

    async def create_organization(self, organization: Organization) -> None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            session.add(_organization_to_row(organization))
            await session.commit()

    async def get_organization(self, org_id: str) -> Organization | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(OrganizationRow, org_id)
            if row is None:
                return None
            return _row_to_organization(row)

    async def list_organizations(self) -> list[Organization]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(OrganizationRow).order_by(
                    OrganizationRow.created_at.desc(),
                    OrganizationRow.id.desc(),
                )
            )
            return [_row_to_organization(row) for row in result.scalars().all()]

    async def create_project(self, project: Project) -> None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            session.add(_project_to_row(project))
            await session.commit()

    async def get_project(self, project_id: str) -> Project | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None:
                return None
            return _row_to_project(row)

    async def list_projects(self, org_id: str) -> list[Project]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(ProjectRow)
                .where(ProjectRow.org_id == org_id)
                .order_by(ProjectRow.created_at.desc(), ProjectRow.id.desc())
            )
            return [_row_to_project(row) for row in result.scalars().all()]

    async def list_all_projects(self) -> list[Project]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(ProjectRow).order_by(
                    ProjectRow.created_at.desc(),
                    ProjectRow.id.desc(),
                )
            )
            return [_row_to_project(row) for row in result.scalars().all()]

    async def list_accessible_projects(self, user_id: str) -> list[Project]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(ProjectRow)
                .join(MembershipRow, MembershipRow.org_id == ProjectRow.org_id)
                .where(MembershipRow.user_id == user_id)
                .order_by(
                    ProjectRow.created_at.desc(),
                    ProjectRow.id.desc(),
                )
            )
            return [_row_to_project(row) for row in result.scalars().all()]

    async def project_slug_taken(
        self,
        org_id: str,
        slug: str,
        *,
        exclude_project_id: str | None = None,
    ) -> bool:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            stmt = select(ProjectRow.id).where(
                ProjectRow.org_id == org_id,
                ProjectRow.slug == slug,
            )
            if exclude_project_id is not None:
                stmt = stmt.where(ProjectRow.id != exclude_project_id)
            result = await session.execute(stmt.limit(1))
            return result.scalar_one_or_none() is not None

    async def rename_project(
        self,
        project_id: str,
        *,
        name: str,
        slug: str,
    ) -> Project | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None:
                return None
            row.name = name
            row.slug = slug
            await session.commit()
            await session.refresh(row)
            return _row_to_project(row)

    async def create_user(self, user: User) -> None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            session.add(_user_to_row(user))
            await session.commit()

    async def get_user(self, user_id: str) -> User | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(UserRow, user_id)
            if row is None:
                return None
            return _row_to_user(row)

    async def get_user_by_subject(self, subject: str) -> User | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(UserRow).where(UserRow.subject == subject)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return _row_to_user(row)

    async def get_user_by_email(self, email: str) -> User | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(select(UserRow).where(UserRow.email == email))
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return _row_to_user(row)

    async def create_membership(self, membership: Membership) -> None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            session.add(_membership_to_row(membership))
            await session.commit()

    async def get_membership(self, membership_id: str) -> Membership | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(MembershipRow, membership_id)
            if row is None:
                return None
            return _row_to_membership(row)

    async def list_memberships(self, org_id: str) -> list[Membership]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(MembershipRow)
                .where(MembershipRow.org_id == org_id)
                .order_by(MembershipRow.created_at.desc(), MembershipRow.id.desc())
            )
            return [_row_to_membership(row) for row in result.scalars().all()]

    async def list_memberships_for_user(self, user_id: str) -> list[Membership]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(MembershipRow)
                .where(MembershipRow.user_id == user_id)
                .order_by(MembershipRow.created_at.desc(), MembershipRow.id.desc())
            )
            return [_row_to_membership(row) for row in result.scalars().all()]

    async def list_accessible_project_ids(self, user_id: str) -> list[str]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(ProjectRow.id)
                .join(MembershipRow, MembershipRow.org_id == ProjectRow.org_id)
                .where(MembershipRow.user_id == user_id)
                .order_by(ProjectRow.created_at.desc(), ProjectRow.id.desc())
            )
            return list(result.scalars().all())

    async def create_ingest_key(
        self,
        project_id: str,
        name: str | None = None,
    ) -> tuple[ProjectIngestKey, str]:
        plaintext = _generate_ingest_token()
        key_hash = _hash_ingest_token(plaintext)
        created_at = datetime.now(UTC)
        key = ProjectIngestKey(
            id=uuid.uuid4().hex,
            project_id=project_id,
            name=name or "",
            key_prefix=plaintext[:12],
            key_hash=key_hash,
            created_at=created_at,
        )
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            session.add(_ingest_key_to_row(key))
            await session.commit()
        return key, plaintext

    async def list_ingest_keys(self, project_id: str) -> list[ProjectIngestKey]:
        return await self.list_ingest_keys_for_projects([project_id])

    async def list_ingest_keys_for_projects(
        self,
        project_ids: Sequence[str] | None,
    ) -> list[ProjectIngestKey]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            stmt = select(ProjectIngestKeyRow).order_by(
                ProjectIngestKeyRow.created_at.desc(),
                ProjectIngestKeyRow.id.desc(),
            )
            if project_ids is not None:
                if len(project_ids) == 0:
                    return []
                stmt = stmt.where(ProjectIngestKeyRow.project_id.in_(project_ids))
            result = await session.execute(stmt)
            keys: list[ProjectIngestKey] = []
            for row in result.scalars().all():
                model = _row_to_ingest_key(row)
                model.key_hash = ""
                keys.append(model)
            return keys

    async def get_ingest_key(self, key_id: str) -> ProjectIngestKey | None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(ProjectIngestKeyRow, key_id)
            if row is None:
                return None
            model = _row_to_ingest_key(row)
            model.key_hash = ""
            return model

    async def resolve_ingest_key(self, plaintext: str) -> ProjectIngestKey | None:
        key_hash = _hash_ingest_token(plaintext)
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(ProjectIngestKeyRow).where(
                    ProjectIngestKeyRow.key_hash == key_hash,
                    ProjectIngestKeyRow.revoked_at.is_(None),
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return _row_to_ingest_key(row)

    async def touch_ingest_key(self, key_id: str) -> None:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(ProjectIngestKeyRow, key_id)
            if row is None:
                return
            row.last_used_at = datetime.now(UTC).isoformat()
            await session.commit()

    async def revoke_ingest_key(self, key_id: str) -> bool:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            row = await session.get(ProjectIngestKeyRow, key_id)
            if row is None:
                return False
            row.revoked_at = datetime.now(UTC).isoformat()
            await session.commit()
            return True


def _generate_ingest_token() -> str:
    return "rpd_" + secrets.token_urlsafe(32)


def _hash_ingest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _resolve_project_id(project_id: str | None) -> str:
    return project_id or DEFAULT_PROJECT_ID


def _exchange_to_row(exchange: Exchange) -> ExchangeRow:
    return ExchangeRow(
        id=exchange.id,
        project_id=_resolve_project_id(exchange.project_id),
        run_id=exchange.run_id,
        parent_run_id=exchange.parent_run_id,
        origin=exchange.origin,
        created_at=exchange.created_at.isoformat(),
        started_at=exchange.started_at.isoformat(),
        ended_at=exchange.ended_at.isoformat(),
        latency_ms=exchange.latency_ms,
        method=exchange.method,
        path=exchange.path,
        query=exchange.query,
        request_headers=json.dumps(exchange.request_headers),
        request_body_hash=exchange.request_body_hash,
        response_status=exchange.response_status,
        response_headers=json.dumps(exchange.response_headers),
        model=exchange.model,
        usage=json.dumps(exchange.usage) if exchange.usage is not None else None,
        provider=exchange.provider,
        response_body_hash=exchange.response_body_hash,
    )


def _row_to_exchange(row: ExchangeRow) -> Exchange:
    return Exchange(
        id=row.id,
        project_id=row.project_id,
        run_id=row.run_id,
        parent_run_id=row.parent_run_id,
        origin=row.origin,
        created_at=datetime.fromisoformat(row.created_at),
        started_at=datetime.fromisoformat(row.started_at),
        ended_at=datetime.fromisoformat(row.ended_at),
        latency_ms=row.latency_ms,
        method=row.method,
        path=row.path,
        query=row.query,
        request_headers=json.loads(row.request_headers),
        request_body_hash=row.request_body_hash,
        response_status=row.response_status,
        response_headers=json.loads(row.response_headers),
        model=row.model,
        usage=json.loads(row.usage) if row.usage is not None else None,
        provider=row.provider,
        response_body_hash=row.response_body_hash,
    )


def _regression_test_to_row(test: RegressionTest) -> RegressionTestRow:
    return RegressionTestRow(
        id=test.id,
        project_id=_resolve_project_id(test.project_id),
        name=test.name,
        baseline_run_id=test.baseline_run_id,
        created_at=test.created_at.isoformat(),
        mode=test.mode,
    )


def _row_to_regression_test(row: RegressionTestRow) -> RegressionTest:
    return RegressionTest(
        id=row.id,
        name=row.name,
        baseline_run_id=row.baseline_run_id,
        project_id=row.project_id,
        created_at=datetime.fromisoformat(row.created_at),
        mode=row.mode or "exact",
    )


def _test_result_to_row(result: TestResult) -> TestResultRow:
    return TestResultRow(
        id=result.id,
        test_id=result.test_id,
        run_at=result.run_at.isoformat(),
        status=result.status,
        total_steps=result.total_steps,
        matched_steps=result.matched_steps,
        first_divergent_step_index=result.first_divergent_step_index,
        detail=result.detail,
        candidate_run_id=result.candidate_run_id,
        step_diffs=json.dumps([diff.model_dump() for diff in result.step_diffs]),
    )


def _row_to_test_result(row: TestResultRow) -> TestResult:
    divergent = row.first_divergent_step_index
    step_diffs_raw = row.step_diffs if row.step_diffs is not None else "[]"
    step_diffs = [StepDiff.model_validate(item) for item in json.loads(step_diffs_raw)]
    return TestResult(
        id=row.id,
        test_id=row.test_id,
        run_at=datetime.fromisoformat(row.run_at),
        status=row.status,
        total_steps=row.total_steps,
        matched_steps=row.matched_steps,
        first_divergent_step_index=int(divergent) if divergent is not None else None,
        detail=row.detail,
        candidate_run_id=row.candidate_run_id,
        step_diffs=step_diffs,
    )


def _organization_to_row(organization: Organization) -> OrganizationRow:
    return OrganizationRow(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        created_at=organization.created_at.isoformat(),
    )


def _row_to_organization(row: OrganizationRow) -> Organization:
    return Organization(
        id=row.id,
        name=row.name,
        slug=row.slug,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _project_to_row(project: Project) -> ProjectRow:
    return ProjectRow(
        id=project.id,
        org_id=project.org_id,
        name=project.name,
        slug=project.slug,
        created_at=project.created_at.isoformat(),
    )


def _row_to_project(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        slug=row.slug,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _user_to_row(user: User) -> UserRow:
    return UserRow(
        id=user.id,
        email=user.email,
        subject=user.subject,
        name=user.name,
        created_at=user.created_at.isoformat(),
    )


def _row_to_user(row: UserRow) -> User:
    return User(
        id=row.id,
        email=row.email,
        subject=row.subject,
        name=row.name,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _membership_to_row(membership: Membership) -> MembershipRow:
    return MembershipRow(
        id=membership.id,
        org_id=membership.org_id,
        user_id=membership.user_id,
        role=membership.role,
        created_at=membership.created_at.isoformat(),
    )


def _row_to_membership(row: MembershipRow) -> Membership:
    return Membership(
        id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        role=row.role,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _ingest_key_to_row(key: ProjectIngestKey) -> ProjectIngestKeyRow:
    return ProjectIngestKeyRow(
        id=key.id,
        project_id=key.project_id,
        name=key.name,
        key_prefix=key.key_prefix,
        key_hash=key.key_hash,
        created_at=key.created_at.isoformat(),
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
        revoked_at=key.revoked_at.isoformat() if key.revoked_at else None,
    )


def _row_to_ingest_key(row: ProjectIngestKeyRow) -> ProjectIngestKey:
    return ProjectIngestKey(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        key_prefix=row.key_prefix,
        key_hash=row.key_hash,
        created_at=datetime.fromisoformat(row.created_at),
        last_used_at=(
            datetime.fromisoformat(row.last_used_at) if row.last_used_at else None
        ),
        revoked_at=(
            datetime.fromisoformat(row.revoked_at) if row.revoked_at else None
        ),
    )


async def list_table_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
