from abc import ABC, abstractmethod
from collections.abc import Sequence



from replayd.models import (

    Exchange,

    Membership,

    Organization,

    Project,

    ProjectIngestKey,

    RegressionTest,

    RunSummary,

    TestResult,

    User,

)





class Storage(ABC):

    @abstractmethod

    async def init(self) -> None:

        """Open connections and ensure schema/directories exist."""



    @abstractmethod

    async def aclose(self) -> None:

        """Release storage resources."""



    @abstractmethod

    async def put_blob(self, data: bytes) -> str:

        """Store bytes and return the sha256 hex digest. Identical blobs dedupe."""



    @abstractmethod

    async def get_blob(self, digest: str) -> bytes:

        """Load bytes by content digest."""



    @abstractmethod

    async def save_exchange(self, exchange: Exchange) -> None:

        """Persist a captured exchange record."""



    @abstractmethod

    async def get_exchange(self, exchange_id: str) -> Exchange | None:

        """Load an exchange by id, or None if missing."""



    @abstractmethod

    async def list_exchanges(

        self,

        limit: int = 100,

        offset: int = 0,

        *,

        project_ids: Sequence[str] | None = None,

    ) -> list[Exchange]:

        """Return exchanges ordered by created_at descending."""



    @abstractmethod

    async def count_exchanges(self, *, project_ids: Sequence[str] | None = None) -> int:

        """Return the total number of stored exchanges."""



    @abstractmethod

    async def list_runs(

        self,

        limit: int = 50,

        offset: int = 0,

        *,

        project_ids: Sequence[str] | None = None,

    ) -> list[RunSummary]:

        """Return run summaries ordered by started_at descending."""



    @abstractmethod

    async def count_runs(self, *, project_ids: Sequence[str] | None = None) -> int:

        """Return the number of distinct runs."""



    @abstractmethod

    async def get_run(self, run_id: str) -> list[Exchange]:

        """Return ordered exchanges for a run, or an empty list if none."""



    @abstractmethod

    async def save_test(self, test: RegressionTest) -> None:

        """Persist a regression test definition."""



    @abstractmethod

    async def get_test(self, test_id: str) -> RegressionTest | None:

        """Load a regression test by id, or None if missing."""



    @abstractmethod

    async def list_tests(

        self,

        *,

        project_ids: Sequence[str] | None = None,

    ) -> list[RegressionTest]:

        """Return regression tests ordered by created_at descending."""



    @abstractmethod

    async def delete_test(self, test_id: str) -> bool:

        """Delete a regression test. Returns True if a row was removed."""



    @abstractmethod

    async def save_test_result(self, result: TestResult) -> None:

        """Persist a regression test run result."""



    @abstractmethod

    async def list_test_results(

        self,

        test_id: str,

        limit: int = 20,

        offset: int = 0,

    ) -> list[TestResult]:

        """Return test results for a test, newest first."""



    @abstractmethod

    async def create_organization(self, organization: Organization) -> None:

        """Persist a new organization."""



    @abstractmethod

    async def get_organization(self, org_id: str) -> Organization | None:

        """Load an organization by id."""



    @abstractmethod

    async def list_organizations(self) -> list[Organization]:

        """Return all organizations ordered by created_at descending."""



    @abstractmethod

    async def create_project(self, project: Project) -> None:

        """Persist a new project."""



    @abstractmethod

    async def get_project(self, project_id: str) -> Project | None:

        """Load a project by id."""



    @abstractmethod

    async def list_projects(self, org_id: str) -> list[Project]:

        """Return projects for an organization ordered by created_at descending."""



    @abstractmethod

    async def create_user(self, user: User) -> None:

        """Persist a new user."""



    @abstractmethod

    async def get_user(self, user_id: str) -> User | None:

        """Load a user by id."""



    @abstractmethod

    async def get_user_by_subject(self, subject: str) -> User | None:

        """Load a user by OIDC subject."""



    @abstractmethod

    async def get_user_by_email(self, email: str) -> User | None:

        """Load a user by email address."""



    @abstractmethod

    async def create_membership(self, membership: Membership) -> None:

        """Persist a new organization membership."""



    @abstractmethod

    async def get_membership(self, membership_id: str) -> Membership | None:

        """Load a membership by id."""



    @abstractmethod

    async def list_memberships(self, org_id: str) -> list[Membership]:

        """Return memberships for an organization."""



    @abstractmethod

    async def list_memberships_for_user(self, user_id: str) -> list[Membership]:

        """Return all organization memberships for a user."""



    @abstractmethod

    async def list_accessible_project_ids(self, user_id: str) -> list[str]:

        """Return project IDs reachable via the user's org memberships."""



    @abstractmethod

    async def create_ingest_key(

        self,

        project_id: str,

        name: str | None = None,

    ) -> tuple[ProjectIngestKey, str]:

        """Create an ingest key; returns the model and the plaintext token once."""



    @abstractmethod

    async def list_ingest_keys(self, project_id: str) -> list[ProjectIngestKey]:

        """Return ingest keys for a project (prefix metadata only, no plaintext)."""



    @abstractmethod

    async def list_ingest_keys_for_projects(

        self,

        project_ids: Sequence[str] | None,

    ) -> list[ProjectIngestKey]:

        """Return ingest keys filtered by project IDs, or all when project_ids is None."""



    @abstractmethod

    async def get_ingest_key(self, key_id: str) -> ProjectIngestKey | None:

        """Return ingest key metadata by id (no plaintext; hash stripped)."""



    @abstractmethod

    async def resolve_ingest_key(self, plaintext: str) -> ProjectIngestKey | None:

        """Resolve a plaintext ingest token to its key, or None if missing/revoked."""



    @abstractmethod

    async def touch_ingest_key(self, key_id: str) -> None:

        """Best-effort update of last_used_at for an ingest key."""



    @abstractmethod

    async def revoke_ingest_key(self, key_id: str) -> bool:

        """Revoke an ingest key. Returns True if a row was updated."""


