# Proto

Use this reference when implementing custom adapters, protocol-compatible models, or package boundaries.

## Package

- Direct install: `uv add belgie-proto`
- Most apps do not install it directly because higher-level Belgie packages depend on it.
- Import contracts from:
  - `belgie_proto.core`
  - `belgie_proto.organization`
  - `belgie_proto.team`
  - `belgie_proto.sso`
  - `belgie_proto.stripe`

## Purpose

`belgie-proto` defines runtime-checkable protocols for the shape Belgie needs:

- accounts
- individuals
- OAuth accounts
- sessions
- OAuth state
- database connections
- core adapters
- organizations, members, invitations
- teams and team members
- SSO providers
- Stripe billing records

The important constraint is satisfying the protocol shape, not inheriting from a concrete base class.

## Adapter Guidance

- Start from `AdapterProtocol` for core auth persistence.
- Implement organization and team protocols only when those plugins are required.
- Keep database-specific behavior inside the adapter.
- Preserve transaction behavior expected by the surrounding app.
- Add protocol or adapter tests for every custom persistence implementation.

Use `belgie-alchemy` instead of custom protocols when SQLAlchemy is acceptable and the app does not need a custom
persistence layer.
