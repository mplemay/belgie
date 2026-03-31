# Belgie Proto: Shared Protocol Interfaces for Belgie Packages

> [!WARNING]
> `belgie-proto` is intentionally low-level. It defines the contracts that other Belgie packages depend on, so changes
> here can ripple across adapters, plugins, and app code that implements these protocols directly.

`belgie-proto` is the contract layer for the Belgie workspace. It defines the runtime-checkable protocols for
customers, individuals, accounts, sessions, OAuth state, adapters, organizations, invitations, teams, and database
connections so the rest of the stack can stay typed without hard-coding a particular ORM or persistence model.

Use it when you are implementing your own adapter, building custom integrations on top of `belgie-core`, or depending
on shared interfaces across multiple Belgie packages. If you want a working SQLAlchemy implementation, start with
[`belgie-alchemy`](../belgie-alchemy/README.md).

## Installation

```bash
uv add belgie-proto
```

> [!NOTE]
> Most applications do not need to install `belgie-proto` directly. It is already pulled in by higher-level Belgie
> packages such as `belgie-core` and `belgie-alchemy`.

## What It Defines

- Core auth protocols for `Customer`, `Individual`, `Account`, `Session`, and `OAuthState`.
- `DBConnection` for the async database/session object passed through Belgie.
- `AdapterProtocol` for core auth persistence operations.
- `OrganizationAdapterProtocol` and `OrganizationTeamAdapterProtocol` for org-aware adapters.
- `TeamAdapterProtocol` for team-aware adapters.
- Shared organization and team model protocols plus error types such as
  `PendingInvitationConflictError`.

## Quick Start

Here is a minimal adapter surface using the core protocols:

```python
from belgie_proto.core import AdapterProtocol, DBConnection, IndividualProtocol


class MyIndividual(IndividualProtocol):
    ...


class MyAdapter(AdapterProtocol):
    async def get_individual_by_email(self, session: DBConnection, email: str) -> MyIndividual | None:
        ...

    async def create_individual(
        self,
        session: DBConnection,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified_at=None,
    ) -> MyIndividual:
        ...

    # implement the rest of AdapterProtocol
```

The important constraint is not inheritance from a base class. It is satisfying the protocol shape that Belgie expects.
That keeps the integration flexible while preserving type checking across packages.

## Namespaces

- Import core auth contracts from `belgie_proto.core`.
- Import organization contracts from `belgie_proto.organization`.
- Import team contracts from `belgie_proto.team`.

## When To Reach For It

- You are writing a custom adapter instead of using `belgie-alchemy`.
- You want package boundaries enforced by protocols instead of concrete ORM models.
- You are extending Belgie with org or team support and need the shared adapter contracts.
