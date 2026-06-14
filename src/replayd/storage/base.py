from abc import ABC, abstractmethod
from collections.abc import Sequence



from replayd.models import (

    Exchange,

    Invitation,

    Membership,

    Organization,

    OrgMember,

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

    async def list_all_projects(self) -> list[Project]:

        """Return all projects ordered by created_at descending."""



    @abstractmethod

    async def list_accessible_projects(self, user_id: str) -> list[Project]:

        """Return projects reachable via the user's org memberships."""



    @abstractmethod

    async def project_slug_taken(

        self,

        org_id: str,

        slug: str,

        *,

        exclude_project_id: str | None = None,

    ) -> bool:

        """Return True when slug is already used within the organization."""



    @abstractmethod

    async def rename_project(

        self,

        project_id: str,

        *,

        name: str,

        slug: str,

    ) -> Project | None:

        """Rename a project and update its slug. Returns None when missing."""



    @abstractmethod

    async def create_user(self, user: User) -> None:

        """Persist a new user."""



    @abstractmethod

    async def update_user_profile(

        self,

        user_id: str,

        *,

        email: str | None = None,

        name: str | None = None,

    ) -> User | None:

        """Update stored user profile fields. Returns None when missing."""



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

    async def get_membership_for_org_user(

        self,

        org_id: str,

        user_id: str,

    ) -> Membership | None:

        """Return a membership for an org/user pair, or None if missing."""



    @abstractmethod

    async def list_memberships_for_org(self, org_id: str) -> list[OrgMember]:

        """Return org members with user email and join time."""



    @abstractmethod

    async def remove_membership(self, org_id: str, user_id: str) -> bool:

        """Remove a user's membership from an org. Returns True if a row was deleted."""



    @abstractmethod

    async def count_owners(self, org_id: str) -> int:

        """Return how many owner-role members belong to the org."""



    @abstractmethod

    async def create_invitation(

        self,

        *,

        org_id: str,

        email: str,

        role: str,

        invited_by_user_id: str,

    ) -> Invitation:

        """Create a pending invitation with generated id and token."""



    @abstractmethod

    async def list_invitations(

        self,

        org_id: str,

        *,

        status: str = "pending",

    ) -> list[Invitation]:

        """Return invitations for an organization filtered by status."""



    @abstractmethod

    async def get_invitation(self, invitation_id: str) -> Invitation | None:

        """Load an invitation by id."""



    @abstractmethod

    async def has_pending_invitation_for_org_email(

        self,

        org_id: str,

        email: str,

    ) -> bool:

        """Return True when a pending invite exists for the org/email pair."""



    @abstractmethod

    async def list_pending_invitations_for_email(self, email: str) -> list[Invitation]:

        """Return pending, unexpired invitations for an email address."""



    @abstractmethod

    async def revoke_invitation(self, invitation_id: str) -> bool:

        """Revoke a pending invitation. Returns True if updated."""



    @abstractmethod

    async def accept_invitation(self, invitation: Invitation, user_id: str) -> None:

        """Accept an invitation, creating membership idempotently."""



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


