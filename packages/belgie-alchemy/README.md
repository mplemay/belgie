# Belgie Alchemy

> [!WARNING]
> Belgie Alchemy is a low-level SQLAlchemy layer. You own the concrete models, migrations, and schema changes in your
> app. It provides mixins and adapters, not a database framework.

Belgie Alchemy is the SQLAlchemy package behind Belgie's auth, organization, and team features. It gives you explicit
adapter wiring and small composable mixins so you can build app-owned models without giving up type safety or clear
schema boundaries.

## Installation

```bash
uv add belgie[alchemy]
```

```bash
uv add belgie[alchemy,organization,team]
```

> [!NOTE]
> Application code should import from `belgie.alchemy`. The implementation package is `belgie_alchemy`, but the
> public re-exports live under `belgie.alchemy`.

## What It Provides

- `BelgieAdapter` for core auth records.
- `OrganizationAdapter` for organization membership and invitations.
- `TeamAdapter` for organization-scoped teams.
- `AccountMixin`, `IndividualMixin`, `OAuthAccountMixin`, `SessionMixin`, and `OAuthStateMixin` for account/auth models.
- `OrganizationMixin`, `OrganizationMemberMixin`, and `OrganizationInvitationMixin` for organization models.
- `TeamMixin` and `TeamMemberMixin` for team models.

## Quick Start

```python
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie.alchemy import AccountMixin, BelgieAdapter, OAuthAccountMixin, OAuthStateMixin, SessionMixin, IndividualMixin


class Individual(DataclassBase, PrimaryKeyMixin, TimestampMixin, IndividualMixin):
    pass


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class OAuthAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


adapter = BelgieAdapter(
    account=Account,
    individual=Individual,
    oauth_account=OAuthAccount,
    session=Session,
    oauth_state=OAuthState,
)
```

This keeps your schema in your application while Belgie handles the adapter contract. You can add custom columns and
relationships on top of the mixins without changing how the adapter works.

## Auth Models

The auth mixins map to the common Belgie records:

- `IndividualMixin` adds email, profile, scopes, and related OAuth account/session/state relationships.
- `AccountMixin` stores the shared account hierarchy fields used by individuals, organizations, and teams.
- `SessionMixin` stores session expiry plus request metadata.
- `OAuthStateMixin` stores OAuth state, PKCE verifier, redirect URL, and optional user linkage.

The default PostgreSQL variants use `CITEXT` for case-insensitive `email`, `provider`, and `provider_account_id`
columns.

> [!NOTE]
> If you use the default PostgreSQL column variants, make sure the `citext` extension is installed in your database.

## Organization And Team

Use the organization and team mixins when your app needs shared org membership plus team-scoped access:

> [!NOTE]
> The snippet below assumes you have already defined `Account`, `Individual`, `OAuthAccount`, `Session`, `OAuthState`,
> `Organization`, `OrganizationMember`, `OrganizationInvitation`, `Team`, and `TeamMember` from the mixins above.

```python
from belgie.alchemy import (
    AccountMixin,
    BelgieAdapter,
    OAuthAccountMixin,
    OAuthStateMixin,
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
    SessionMixin,
    TeamMemberMixin,
    TeamMixin,
    IndividualMixin,
)
from belgie.alchemy.organization import OrganizationAdapter
from belgie.alchemy.team import TeamAdapter

core_adapter = BelgieAdapter(
    account=Account,
    individual=Individual,
    oauth_account=OAuthAccount,
    session=Session,
    oauth_state=OAuthState,
)

# Organizations only (no team plugin)
organization_adapter = OrganizationAdapter(
    organization=Organization,
    member=OrganizationMember,
    invitation=OrganizationInvitation,
)

# Organization + team plugins: one adapter for both plugins
team_adapter = TeamAdapter(
    organization=Organization,
    member=OrganizationMember,
    invitation=OrganizationInvitation,
    team=Team,
    team_member=TeamMember,
)
```

When you enable both plugins, use the team-capable adapter for both. If you only need organizations, the organization
adapter is sufficient.

The default PostgreSQL variants also use `CITEXT` for organization `slug` values and pending invitation `email`
addresses. Pending invitations are unique per `(organization_id, email)` while their status is `pending`.

## Examples

- [`examples/alchemy/auth_models.py`](../../examples/alchemy/auth_models.py) for a compact auth-model reference.
- [`examples/organization_team`](../../examples/organization_team) for a runnable organization + team app.
