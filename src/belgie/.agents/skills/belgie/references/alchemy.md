# Alchemy

Use this reference for SQLAlchemy models, Belgie mixins, concrete adapters, and database schema ownership.

## Package

- Umbrella install: `uv add "belgie[alchemy]"`
- Direct package install: `uv add belgie-alchemy`
- Application imports should usually come from `belgie.alchemy`.

## Core Adapter

`BelgieAdapter` requires app-owned SQLAlchemy model classes:

```python
from belgie.alchemy import BelgieAdapter

adapter = BelgieAdapter(
    account=Account,
    individual=Individual,
    oauth_account=OAuthAccount,
    session=Session,
    oauth_state=OAuthState,
)
```

The application owns table names, migrations, relationships, and custom columns. Belgie provides mixins and adapter
logic, not a migration framework.

## Mixins

Use the core mixins for auth models:

- `AccountMixin`
- `IndividualMixin`
- `OAuthAccountMixin`
- `SessionMixin`
- `OAuthStateMixin`

Use plugin mixins only when that plugin is installed:

- OAuth server: `OAuthServerClientMixin`, authorization state/code mixins, access/refresh token mixins, consent mixin
- Organization: `OrganizationMixin`, `OrganizationMemberMixin`, `OrganizationInvitationMixin`
- Team: `TeamMixin`, `TeamMemberMixin`
- SSO: `SSOProviderMixin`
- Stripe: `StripeAccountMixin`, `StripeSubscriptionMixin`

## Organization And Team Adapters

Use `OrganizationAdapter` only for organization-only apps. When teams are enabled, use the team-capable adapter for
both organization and team plugins:

```python
from belgie.alchemy.team import TeamAdapter

team_adapter = TeamAdapter(
    organization=OrganizationModel,
    member=OrganizationMember,
    invitation=OrganizationInvitation,
    team=TeamModel,
    team_member=TeamMember,
)
```

## Database Notes

- Keep `AsyncSession` dependencies as FastAPI `yield` dependencies.
- Commit/rollback behavior belongs in adapters and app services, not route handlers.
- PostgreSQL variants may use `CITEXT` for case-insensitive email, provider, and slug fields. Ensure the extension is
  installed when using those columns.
- Add tests around adapter behavior when introducing custom fields or model inheritance.
