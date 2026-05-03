# Account Model

Use this reference when deciding how `Account`, `Individual`, `Organization`, and `Team` fit together.

Belgie separates the authenticated human from billable or organizational account targets. In SQLAlchemy-backed apps,
`Account` is the shared polymorphic base table and `Individual`, `Organization`, and `Team` are account subtypes.

## Account

`Account` is the shared base for anything that can be addressed as an account. The Belgie Alchemy mixin adds:

- `account_type`, using `AccountType.INDIVIDUAL`, `AccountType.ORGANIZATION`, or `AccountType.TEAM`
- shared `name`
- shared `id`, `created_at`, and `updated_at` when composed with the app's base mixins

The core adapter accepts the `account` model and exposes generic account lookup and update behavior. Use account-level
operations when a feature is intentionally account-agnostic, such as Stripe billing.

## Individual

`Individual` is the authenticated human user. Core auth dependencies return individuals, not generic accounts.

Sessions, OAuth provider accounts, and OAuth state rows attach to `Individual`:

- `OAuthAccount.individual_id`
- `Session.individual_id`
- `OAuthState.individual_id`

Use `Depends(belgie.individual)` or `Security(belgie.individual, scopes=[...])` when protecting app routes.

## Organization

`Organization` is an account subtype for tenant or workspace ownership. It adds organization-specific fields such as
`slug` and `logo`.

Organization membership is represented by `OrganizationMember`, which links an individual to an organization with a
role. Invitations are represented by `OrganizationInvitation`, which stores the invited email, role, status, inviter,
expiration, and optional `team_id`.

Organization routes are app-owned. Register the organization plugin, inject `OrganizationClient`, and expose only the
routes your product needs.

## Team

`Team` is an account subtype scoped to exactly one organization through `organization_id`.

Team membership is represented by `TeamMember`, which links an individual to a team. An individual must be an
organization member before they can become a team member. Team creation and membership management require organization
owner or admin permissions by default.

When an organization invitation includes `team_id`, accepting the invitation can create both organization membership and
team membership.

## Practical Rules

- Use `Individual` for authentication, sessions, OAuth sign-in, route protection, and user profile state.
- Use `Organization` for tenant/workspace membership, roles, invitations, and organization-scoped policy.
- Use `Team` for subdivisions inside an organization, never as a standalone tenant outside an organization.
- Use generic `Account` ids only for features designed to work across individuals, organizations, and teams.
- Stripe billing targets generic `Account` records, while core auth dependencies still return `Individual`.
