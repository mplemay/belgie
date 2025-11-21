# Design Document: belgie.ab - A/B Testing Module

**Author**: Claude
**Date**: 2025-11-21
**Status**: Proposal

---

## Executive Summary

This document proposes the design of `belgie.ab`, an A/B testing and experimentation module for the belgie framework. The module will provide tight integration with FastAPI, authentication, sessions, and observability while following belgie's protocol-based architecture patterns.

---

## 1. Research Findings

### 1.1 Belgie Framework Analysis

**Architecture Overview:**
- **Protocol-based design**: Type-safe interfaces with zero coupling to concrete implementations
- **Async-first**: Built on SQLAlchemy 2.0+ async, designed for FastAPI
- **Dependency injection**: Leverages FastAPI's DI system extensively
- **Pydantic configuration**: Environment-based settings with strong typing
- **Session management**: Database-backed with sliding window refresh
- **Auth integration**: OAuth 2.0 flow with scope-based authorization
- **No existing observability**: Clean slate for tracing/metrics

**Key Integration Points:**
1. **User Model** (`UserProtocol`): Contains `id`, `email`, `scopes`, custom fields possible
2. **Session Model** (`SessionProtocol`): Tracks `user_id`, `expires_at`, `ip_address`, `user_agent`
3. **FastAPI Dependencies**: Pattern for route protection and context injection
4. **AlchemyAdapter**: Async database operations pattern
5. **Settings**: Pydantic BaseSettings with environment variable loading

### 1.2 Industry A/B Testing Patterns

#### Commercial Platforms

**LaunchDarkly**
- Client-side evaluation with CDN delivery
- Streaming updates (not polling)
- Flag hierarchy with prerequisites
- Flags as control points for delivery, observability, and experimentation
- Context-based targeting

**Optimizely / Split.io**
- Statistical analysis built-in (CUPED, Sequential testing, Bayesian)
- Metric tracking and alerting
- Multi-armed bandit support
- Rich SDKs with automatic metric collection

#### Open Source Solutions

**GrowthBook (Python)**
- MIT licensed, async-friendly
- Server-Sent Events for real-time updates
- Feature flag experiments
- Visual experiment builder
- Encrypted feature payloads
- Works with FastAPI

**Unleash (Node.js)**
- Open source feature management
- Activation strategies: gradual rollout, user targeting, custom contexts
- Metrics collection
- Impression data for analytics integration

**Split (Ruby)**
- Redis-backed storage
- Built-in dashboard
- Conversion tracking
- Simple `ab_test` / `ab_finished` API

**FF4j / Togglz (Java/Spring)**
- AOP-based feature toggling
- Multiple activation strategies
- Web console included
- 20+ database support (FF4j)

### 1.3 Technical Patterns

#### Variant Assignment Algorithms

**Hash-Based Bucketing** (Industry Standard):
```python
def assign_variant(experiment_name: str, user_id: str, num_variants: int) -> int:
    """Deterministic variant assignment using hashing."""
    # 1. Concatenate experiment name + user identifier
    input_string = f"{experiment_name}:{user_id}"

    # 2. Hash using MD5/SHA-256/MurmurHash
    hash_digest = hashlib.md5(input_string.encode()).hexdigest()

    # 3. Convert to integer in range [0, 1)
    hash_int = int(hash_digest, 16)
    hash_float = hash_int / (2 ** 128)  # For MD5

    # 4. Map to variant bucket
    return int(hash_float * num_variants)
```

**Benefits:**
- Deterministic: Same user always gets same variant
- Uniform distribution across variants
- No database lookup required for assignment
- Scales to millions of users
- Test name as salt prevents correlation between experiments

**Common Hash Functions:**
- MD5: Fast, good distribution, 128-bit
- SHA-256: More secure, 256-bit
- MurmurHash3: Very fast, used by Optimizely
- FNV-1a: Simple, fast

#### Activation Strategies

Common patterns across frameworks:
1. **Gradual Rollout**: Percentage-based user exposure
2. **User Targeting**: Whitelist/blacklist by user attributes
3. **Release Date**: Time-based activation
4. **Custom Rules**: Complex boolean logic on user context

#### Sticky Bucketing

Ensures users stay in same variant even if experiment allocation changes:
- Store `{user_id, experiment_id} → variant_id` mapping
- Check stored assignment before hash-based calculation
- Prevents user experience inconsistency

---

## 2. Design Constraints

### 2.1 Must Have
- **Protocol-based architecture**: Follow belgie's patterns
- **FastAPI integration**: Dependency injection, middleware, or decorators
- **Auth/session awareness**: Leverage existing user/session data
- **Type safety**: Full typing with Protocols
- **Async support**: Async/await throughout
- **Database agnostic**: Use adapter pattern like `AlchemyAdapter`
- **Simple API**: Easy to use for common cases

### 2.2 Nice to Have
- **Observability integration**: Tracing, metrics, events
- **Real-time updates**: SSE or WebSocket for flag changes
- **Statistical analysis**: Built-in or plugin architecture
- **Visual dashboard**: Web UI for experiment management
- **Multi-variate testing**: Beyond A/B to A/B/C/D...

### 2.3 Out of Scope (v1)
- Visual experiment editor (can use external tools)
- Advanced statistics (Bayesian, CUPED) - focus on assignment
- AI-powered optimization
- CDN-based flag delivery

---

## 3. Design Proposals

### Proposal A: Lightweight Decorator-Based Design

**Philosophy**: Minimal, decorator-driven, zero external dependencies

**Core Components:**

```python
# belgie/ab/core/experiment.py
from typing import Protocol, Callable, Any
from dataclasses import dataclass
from enum import Enum

@dataclass
class Variant:
    """A single variant in an experiment."""
    name: str
    weight: float  # 0.0 to 1.0

@dataclass
class Experiment:
    """Definition of an A/B test."""
    name: str
    variants: list[Variant]
    enabled: bool = True

class ABTest:
    """Main A/B testing engine."""

    def __init__(self, experiments: dict[str, Experiment]):
        self.experiments = experiments

    def assign_variant(
        self,
        experiment_name: str,
        user_id: str
    ) -> str:
        """Assign user to variant using hash-based bucketing."""
        experiment = self.experiments[experiment_name]

        if not experiment.enabled:
            return experiment.variants[0].name  # Control

        # Hash-based assignment
        hash_value = self._hash(f"{experiment_name}:{user_id}")

        # Map to variant based on weights
        cumulative = 0.0
        for variant in experiment.variants:
            cumulative += variant.weight
            if hash_value < cumulative:
                return variant.name

        return experiment.variants[-1].name

    def _hash(self, input_string: str) -> float:
        """Hash string to float in [0, 1)."""
        import hashlib
        hash_bytes = hashlib.md5(input_string.encode()).digest()
        hash_int = int.from_bytes(hash_bytes, byteorder='big')
        return hash_int / (2 ** 128)

# belgie/ab/dependencies.py
from fastapi import Depends, Request
from belgie.auth import Auth

async def get_variant(
    request: Request,
    experiment_name: str,
    user = Depends(auth.user),  # Reuse auth
    ab_test: ABTest = Depends(get_ab_test)
) -> str:
    """FastAPI dependency to get user's variant."""
    return ab_test.assign_variant(experiment_name, str(user.id))

# Usage in routes
@app.get("/new-feature")
async def new_feature(
    user = Depends(auth.user),
    variant: str = Depends(lambda: get_variant(experiment_name="homepage_redesign"))
):
    if variant == "control":
        return render_old_homepage()
    elif variant == "treatment":
        return render_new_homepage()
```

**Configuration:**
```python
# settings.py
from pydantic import BaseSettings

class ABSettings(BaseSettings):
    experiments: dict[str, dict] = {
        "homepage_redesign": {
            "enabled": True,
            "variants": [
                {"name": "control", "weight": 0.5},
                {"name": "treatment", "weight": 0.5}
            ]
        }
    }

    class Config:
        env_prefix = "BELGIE_AB_"
```

**Pros:**
- Extremely simple, minimal code
- No database required for assignments
- Fast (in-memory evaluation)
- Easy to understand
- Follows functional programming style

**Cons:**
- No persistence of assignments (sticky bucketing requires addon)
- No built-in analytics
- Configuration changes require restart
- No targeting beyond user_id

---

### Proposal B: Database-Backed with Observability

**Philosophy**: Full-featured with persistence, observability, and flexibility

**Architecture:**

```
belgie/ab/
├── core/
│   ├── engine.py          # Main ABEngine class
│   ├── assignment.py      # Variant assignment logic
│   ├── evaluation.py      # Rule evaluation
│   ├── settings.py        # Configuration models
│   └── exceptions.py      # ABError, ExperimentNotFound, etc.
├── adapters/
│   └── alchemy.py         # Database adapter
├── protocols/
│   └── models.py          # ExperimentProtocol, AssignmentProtocol, EventProtocol
├── middleware/
│   └── tracking.py        # Request middleware for automatic tracking
└── dependencies.py        # FastAPI dependencies
```

**Database Models (Protocols):**

```python
# protocols/models.py
from typing import Protocol
from uuid import UUID
from datetime import datetime

class ExperimentProtocol(Protocol):
    """Protocol for experiment storage."""
    id: UUID
    name: str                    # Unique identifier
    description: str | None
    enabled: bool
    variants: dict[str, float]   # {"control": 0.5, "treatment": 0.5}
    targeting_rules: dict | None # JSON rules for user targeting
    created_at: datetime
    updated_at: datetime

class AssignmentProtocol(Protocol):
    """Protocol for sticky bucketing."""
    id: UUID
    experiment_id: UUID
    user_id: UUID
    variant: str
    assigned_at: datetime

class EventProtocol(Protocol):
    """Protocol for tracking experiment events."""
    id: UUID
    experiment_id: UUID
    user_id: UUID
    session_id: UUID | None
    variant: str
    event_type: str              # "exposure", "conversion", "custom"
    event_name: str | None
    properties: dict | None       # JSON metadata
    timestamp: datetime
```

**Core Engine:**

```python
# core/engine.py
from typing import Generic, TypeVar
from belgie.auth.protocols import UserProtocol

ExperimentT = TypeVar("ExperimentT", bound=ExperimentProtocol)
AssignmentT = TypeVar("AssignmentT", bound=AssignmentProtocol)
EventT = TypeVar("EventT", bound=EventProtocol)

class ABEngine(Generic[ExperimentT, AssignmentT, EventT]):
    """Main A/B testing engine with persistence."""

    def __init__(
        self,
        adapter: ABAdapter[ExperimentT, AssignmentT, EventT],
        settings: ABSettings
    ):
        self.adapter = adapter
        self.settings = settings

    async def get_variant(
        self,
        db: AsyncSession,
        experiment_name: str,
        user_id: UUID,
        user_context: dict | None = None
    ) -> str:
        """Get user's variant with sticky bucketing."""

        # 1. Load experiment
        experiment = await self.adapter.get_experiment_by_name(db, experiment_name)
        if not experiment or not experiment.enabled:
            return list(experiment.variants.keys())[0]  # Return control

        # 2. Check for existing assignment (sticky bucketing)
        assignment = await self.adapter.get_assignment(db, experiment.id, user_id)
        if assignment:
            return assignment.variant

        # 3. Evaluate targeting rules
        if experiment.targeting_rules:
            if not self._matches_targeting(experiment.targeting_rules, user_context):
                return list(experiment.variants.keys())[0]  # Not in target

        # 4. Hash-based assignment
        variant = self._assign_variant(experiment_name, str(user_id), experiment.variants)

        # 5. Persist assignment
        await self.adapter.create_assignment(
            db,
            experiment_id=experiment.id,
            user_id=user_id,
            variant=variant
        )

        # 6. Track exposure event
        if self.settings.track_exposures:
            await self.track_event(
                db,
                experiment_id=experiment.id,
                user_id=user_id,
                variant=variant,
                event_type="exposure"
            )

        return variant

    async def track_event(
        self,
        db: AsyncSession,
        experiment_id: UUID,
        user_id: UUID,
        variant: str,
        event_type: str,
        event_name: str | None = None,
        properties: dict | None = None,
        session_id: UUID | None = None
    ) -> EventT:
        """Track an experiment event (exposure, conversion, etc.)."""
        return await self.adapter.create_event(
            db,
            experiment_id=experiment_id,
            user_id=user_id,
            session_id=session_id,
            variant=variant,
            event_type=event_type,
            event_name=event_name,
            properties=properties
        )

    def _assign_variant(
        self,
        experiment_name: str,
        user_id: str,
        variants: dict[str, float]
    ) -> str:
        """Hash-based variant assignment."""
        import hashlib

        hash_digest = hashlib.md5(f"{experiment_name}:{user_id}".encode()).digest()
        hash_int = int.from_bytes(hash_digest, byteorder='big')
        hash_float = hash_int / (2 ** 128)

        cumulative = 0.0
        for variant_name, weight in variants.items():
            cumulative += weight
            if hash_float < cumulative:
                return variant_name

        return list(variants.keys())[-1]

    def _matches_targeting(self, rules: dict, context: dict | None) -> bool:
        """Evaluate targeting rules against user context."""
        # Simple rule evaluation (can be extended)
        if not context:
            return True

        for key, expected_value in rules.items():
            if context.get(key) != expected_value:
                return False
        return True
```

**FastAPI Integration:**

```python
# dependencies.py
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

async def get_experiment_variant(
    experiment_name: str,
    request: Request,
    user = Depends(auth.user),
    session = Depends(auth.session),
    db: AsyncSession = Depends(get_db),
    ab_engine: ABEngine = Depends(get_ab_engine)
) -> str:
    """Dependency to get user's variant for an experiment."""

    # Build user context from auth data
    user_context = {
        "user_id": str(user.id),
        "email": user.email,
        "scopes": user.scopes,
        "ip_address": session.ip_address if session else None,
        "user_agent": session.user_agent if session else None
    }

    variant = await ab_engine.get_variant(
        db,
        experiment_name=experiment_name,
        user_id=user.id,
        user_context=user_context
    )

    return variant

# Decorator for easier use
def experiment(name: str, variants: list[str]):
    """Decorator to run different code paths based on variant."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract variant from kwargs (injected by dependency)
            variant = kwargs.get("variant")

            # Call appropriate handler
            handler = kwargs.get(f"handle_{variant}", func)
            return await handler(*args, **kwargs)

        return wrapper
    return decorator

# Usage
@app.get("/dashboard")
@experiment(name="dashboard_redesign", variants=["control", "treatment"])
async def dashboard(
    user = Depends(auth.user),
    variant: str = Depends(lambda req, u=Depends(auth.user):
        get_experiment_variant("dashboard_redesign", req, u))
):
    if variant == "control":
        return {"version": "old"}
    else:
        return {"version": "new"}
```

**Middleware for Automatic Tracking:**

```python
# middleware/tracking.py
from starlette.middleware.base import BaseHTTPMiddleware

class ExperimentTrackingMiddleware(BaseHTTPMiddleware):
    """Automatically track experiment exposures."""

    def __init__(self, app, ab_engine: ABEngine):
        super().__init__(app)
        self.ab_engine = ab_engine

    async def dispatch(self, request, call_next):
        # Store experiment exposures in request state
        request.state.experiment_exposures = []

        response = await call_next(request)

        # Track all exposures after response
        if hasattr(request.state, "experiment_exposures"):
            for exposure in request.state.experiment_exposures:
                await self.ab_engine.track_event(
                    db=exposure["db"],
                    experiment_id=exposure["experiment_id"],
                    user_id=exposure["user_id"],
                    variant=exposure["variant"],
                    event_type="exposure"
                )

        return response
```

**Pros:**
- Full persistence with sticky bucketing
- Built-in event tracking for analytics
- Targeting rules support
- Follows belgie's protocol-based architecture
- Observability-ready
- Scales well with proper indexing

**Cons:**
- More complex implementation
- Requires database migrations
- More database queries per request
- Needs cache layer for high-scale

---

### Proposal C: Hybrid - Simple Core + Optional Persistence

**Philosophy**: Start simple (Proposal A), add persistence as optional addon

**Core (No Database):**

```python
# belgie/ab/core.py
from dataclasses import dataclass
from typing import Callable

@dataclass
class Experiment:
    name: str
    variants: dict[str, float]
    enabled: bool = True

class ABTest:
    """Lightweight A/B testing without persistence."""

    def __init__(self, experiments: dict[str, Experiment]):
        self.experiments = experiments
        self._assignment_override: dict[tuple[str, str], str] = {}

    def assign_variant(self, experiment_name: str, user_id: str) -> str:
        """Assign variant using hash bucketing."""
        # Check manual override first
        key = (experiment_name, user_id)
        if key in self._assignment_override:
            return self._assignment_override[key]

        experiment = self.experiments.get(experiment_name)
        if not experiment or not experiment.enabled:
            return "control"

        return self._hash_assign(experiment_name, user_id, experiment.variants)

    def override_assignment(self, experiment_name: str, user_id: str, variant: str):
        """Manually override assignment (for testing)."""
        self._assignment_override[(experiment_name, user_id)] = variant

    def _hash_assign(self, exp_name: str, user_id: str, variants: dict[str, float]) -> str:
        import hashlib
        hash_val = hashlib.md5(f"{exp_name}:{user_id}".encode()).digest()
        hash_float = int.from_bytes(hash_val, byteorder='big') / (2 ** 128)

        cumulative = 0.0
        for variant, weight in variants.items():
            cumulative += weight
            if hash_float < cumulative:
                return variant
        return list(variants.keys())[-1]
```

**Optional Persistence Extension:**

```python
# belgie/ab/extensions/persistence.py
from belgie.ab.core import ABTest

class PersistentABTest(ABTest):
    """ABTest with database-backed sticky bucketing."""

    def __init__(
        self,
        experiments: dict[str, Experiment],
        adapter: ABAdapter  # Optional
    ):
        super().__init__(experiments)
        self.adapter = adapter

    async def assign_variant(
        self,
        db: AsyncSession,
        experiment_name: str,
        user_id: str
    ) -> str:
        """Assign with sticky bucketing if adapter provided."""

        if self.adapter:
            # Check DB for existing assignment
            assignment = await self.adapter.get_assignment(
                db, experiment_name, user_id
            )
            if assignment:
                return assignment.variant

        # Fall back to hash-based
        variant = super().assign_variant(experiment_name, user_id)

        if self.adapter:
            # Persist assignment
            await self.adapter.create_assignment(
                db, experiment_name, user_id, variant
            )

        return variant
```

**Optional Tracking Extension:**

```python
# belgie/ab/extensions/tracking.py

class TrackingABTest(PersistentABTest):
    """ABTest with event tracking."""

    async def assign_variant(self, db, experiment_name, user_id):
        variant = await super().assign_variant(db, experiment_name, user_id)

        if self.adapter:
            await self.adapter.track_event(
                db,
                experiment_name=experiment_name,
                user_id=user_id,
                variant=variant,
                event_type="exposure"
            )

        return variant

    async def track_conversion(
        self,
        db: AsyncSession,
        experiment_name: str,
        user_id: str,
        conversion_name: str,
        properties: dict | None = None
    ):
        """Track a conversion event."""
        # Get user's variant first
        assignment = await self.adapter.get_assignment(db, experiment_name, user_id)

        if assignment:
            await self.adapter.track_event(
                db,
                experiment_name=experiment_name,
                user_id=user_id,
                variant=assignment.variant,
                event_type="conversion",
                event_name=conversion_name,
                properties=properties
            )
```

**Usage - Start Simple:**

```python
from belgie.ab import ABTest, Experiment

# Simple in-memory testing
ab_test = ABTest(experiments={
    "homepage": Experiment(
        name="homepage",
        variants={"control": 0.5, "new_design": 0.5}
    )
})

@app.get("/")
async def homepage(user = Depends(auth.user)):
    variant = ab_test.assign_variant("homepage", str(user.id))
    return render_template(f"homepage_{variant}.html")
```

**Usage - Add Persistence Later:**

```python
from belgie.ab.extensions import PersistentABTest
from belgie.ab.adapters import AlchemyABAdapter

# Add sticky bucketing
adapter = AlchemyABAdapter(...)
ab_test = PersistentABTest(experiments={...}, adapter=adapter)

@app.get("/")
async def homepage(
    user = Depends(auth.user),
    db = Depends(get_db)
):
    variant = await ab_test.assign_variant(db, "homepage", str(user.id))
    return render_template(f"homepage_{variant}.html")
```

**Usage - Add Tracking:**

```python
from belgie.ab.extensions import TrackingABTest

ab_test = TrackingABTest(experiments={...}, adapter=adapter)

@app.post("/checkout")
async def checkout(
    user = Depends(auth.user),
    db = Depends(get_db)
):
    variant = await ab_test.assign_variant(db, "checkout_flow", str(user.id))

    # Process checkout...

    # Track conversion
    await ab_test.track_conversion(
        db,
        experiment_name="checkout_flow",
        user_id=str(user.id),
        conversion_name="purchase",
        properties={"amount": 99.99}
    )

    return {"status": "success"}
```

**Pros:**
- Progressive enhancement - start simple, add features as needed
- Low barrier to entry
- Clear upgrade path
- Simple cases stay simple
- Complex cases possible
- Follows open/closed principle

**Cons:**
- API surface grows with extensions
- Need to document upgrade path clearly
- Potential confusion about which class to use

---

## 4. Recommendation

**Recommended Approach: Proposal C (Hybrid)**

**Rationale:**

1. **Matches belgie's philosophy**: Start with minimal, type-safe core
2. **Progressive disclosure**: Simple use cases don't pay complexity tax
3. **Clear upgrade path**: Add persistence/tracking when needed
4. **Flexibility**: Works for small apps and large-scale apps
5. **Testability**: In-memory testing is trivial, no mocks needed
6. **Learning curve**: Gentle - start with simple API

**Implementation Plan:**

### Phase 1: Core (Week 1)
- [ ] `belgie/ab/core.py` - Hash-based assignment
- [ ] `belgie/ab/dependencies.py` - FastAPI integration
- [ ] `belgie/ab/settings.py` - Configuration models
- [ ] Tests for hash consistency and distribution
- [ ] Basic documentation

### Phase 2: Persistence (Week 2)
- [ ] `belgie/ab/protocols/models.py` - ExperimentProtocol, AssignmentProtocol
- [ ] `belgie/ab/adapters/alchemy.py` - SQLAlchemy adapter
- [ ] `belgie/ab/extensions/persistence.py` - PersistentABTest
- [ ] Database migrations
- [ ] Tests for sticky bucketing

### Phase 3: Tracking (Week 3)
- [ ] `belgie/ab/protocols/models.py` - EventProtocol
- [ ] `belgie/ab/extensions/tracking.py` - TrackingABTest
- [ ] `belgie/ab/middleware/tracking.py` - Automatic exposure tracking
- [ ] Event storage and querying
- [ ] Tests for event tracking

### Phase 4: Polish (Week 4)
- [ ] Targeting rules engine
- [ ] Admin utilities for managing experiments
- [ ] Export utilities for analytics
- [ ] Comprehensive documentation
- [ ] Example applications

---

## 5. API Examples

### Basic Usage

```python
from belgie.ab import ABTest, Experiment, Depends

ab_test = ABTest(experiments={
    "button_color": Experiment(
        name="button_color",
        variants={"red": 0.5, "blue": 0.5}
    )
})

@app.get("/landing")
async def landing(user = Depends(auth.user)):
    variant = ab_test.assign_variant("button_color", str(user.id))
    return {"button_color": variant}
```

### With Sticky Bucketing

```python
from belgie.ab.extensions import PersistentABTest

ab_test = PersistentABTest(experiments={...}, adapter=adapter)

@app.get("/feature")
async def feature(
    user = Depends(auth.user),
    db = Depends(get_db)
):
    variant = await ab_test.assign_variant(db, "new_feature", str(user.id))

    if variant == "enabled":
        return new_feature_response()
    else:
        return old_feature_response()
```

### With Conversion Tracking

```python
from belgie.ab.extensions import TrackingABTest

ab_test = TrackingABTest(experiments={...}, adapter=adapter)

@app.post("/signup")
async def signup(
    data: SignupData,
    user = Depends(auth.user),
    db = Depends(get_db)
):
    # User sees experiment
    variant = await ab_test.assign_variant(db, "signup_flow", str(user.id))

    # Show appropriate signup form...
    result = process_signup(data, variant)

    # Track conversion
    if result.success:
        await ab_test.track_conversion(
            db,
            experiment_name="signup_flow",
            user_id=str(user.id),
            conversion_name="signup_completed",
            properties={"plan": data.plan}
        )

    return result
```

### With Dependency Injection

```python
from belgie.ab.dependencies import experiment_variant

@app.get("/dashboard")
async def dashboard(
    user = Depends(auth.user),
    variant: str = Depends(experiment_variant("dashboard_v2"))
):
    if variant == "control":
        return render_old_dashboard(user)
    else:
        return render_new_dashboard(user)
```

### Manual Conversion Tracking

```python
@app.post("/purchase")
async def purchase(
    item: Item,
    user = Depends(auth.user),
    db = Depends(get_db)
):
    # Process purchase...

    # Track as conversion for all active experiments
    experiments_to_track = ["checkout_redesign", "pricing_test"]

    for exp_name in experiments_to_track:
        await ab_test.track_conversion(
            db,
            experiment_name=exp_name,
            user_id=str(user.id),
            conversion_name="purchase",
            properties={"amount": item.price}
        )

    return {"status": "success"}
```

---

## 6. Database Schema (Phase 2+)

```sql
-- Experiments table
CREATE TABLE experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    variants JSONB NOT NULL,  -- {"control": 0.5, "treatment": 0.5}
    targeting_rules JSONB,    -- {"scopes": ["ADMIN"], "email_domain": "company.com"}
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Assignments table (sticky bucketing)
CREATE TABLE ab_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID REFERENCES experiments(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    variant VARCHAR(255) NOT NULL,
    assigned_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(experiment_id, user_id)
);
CREATE INDEX idx_assignments_user ON ab_assignments(user_id);
CREATE INDEX idx_assignments_experiment ON ab_assignments(experiment_id);

-- Events table (tracking)
CREATE TABLE ab_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID REFERENCES experiments(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    session_id UUID,
    variant VARCHAR(255) NOT NULL,
    event_type VARCHAR(50) NOT NULL,  -- exposure, conversion, custom
    event_name VARCHAR(255),
    properties JSONB,
    timestamp TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_events_experiment ON ab_events(experiment_id);
CREATE INDEX idx_events_user ON ab_events(user_id);
CREATE INDEX idx_events_type ON ab_events(event_type);
CREATE INDEX idx_events_timestamp ON ab_events(timestamp);
```

---

## 7. Configuration

```python
# belgie/ab/settings.py
from pydantic import BaseSettings

class ABSettings(BaseSettings):
    """Configuration for A/B testing module."""

    # Core settings
    hash_function: str = "md5"  # md5, sha256, murmur3

    # Tracking settings
    track_exposures: bool = True
    track_anonymous_users: bool = False

    # Performance settings
    cache_experiments: bool = True
    cache_ttl: int = 300  # seconds

    # Database settings
    use_persistence: bool = False
    use_tracking: bool = False

    class Config:
        env_prefix = "BELGIE_AB_"

# Environment variables:
# BELGIE_AB_HASH_FUNCTION=sha256
# BELGIE_AB_TRACK_EXPOSURES=true
# BELGIE_AB_USE_PERSISTENCE=true
```

---

## 8. Open Questions

1. **Session vs User ID**: Should we support session-based experiments for anonymous users?
   - **Recommendation**: Yes, use session_id if user not authenticated

2. **Real-time updates**: Should experiments update without restart?
   - **Recommendation**: Phase 5 feature, use Redis pub/sub or SSE

3. **Statistical analysis**: Built-in or external?
   - **Recommendation**: External initially, provide export utilities

4. **Multi-variate testing**: How many variants to support?
   - **Recommendation**: No hard limit, but recommend 2-4 for statistical power

5. **Integration with auth scopes**: Should experiments be scope-aware by default?
   - **Recommendation**: Yes, include user.scopes in default context

---

## 9. Success Metrics

How do we know this design is successful?

1. **Adoption**: Belgie users actually use `belgie.ab` in production
2. **Simplicity**: New users can run first A/B test in < 5 minutes
3. **Performance**: < 5ms overhead per request with hash-based assignment
4. **Flexibility**: Advanced users can build custom features on top
5. **Type safety**: Zero runtime type errors in production

---

## 10. Alternatives Considered

### Alternative 1: Embed in Auth Module
Put A/B testing directly in `belgie.auth` as a sub-feature.

**Rejected because:**
- A/B testing is orthogonal to auth
- Not all auth users need A/B testing
- Violates single responsibility principle

### Alternative 2: Pure Feature Flags (No A/B Testing)
Build only feature flags without variant assignment.

**Rejected because:**
- Market wants both feature flags AND A/B testing
- Hash-based assignment is trivial to add
- Tracking is key differentiator

### Alternative 3: External Service Only
Force users to use external services (LaunchDarkly, Split.io).

**Rejected because:**
- Vendor lock-in
- Additional cost
- Network dependency
- Doesn't match belgie's self-hosted philosophy

---

## 11. Next Steps

1. **Gather feedback** on this design document
2. **Prototype** Proposal C core (1-2 days)
3. **User testing** with simple example app
4. **Iterate** based on feedback
5. **Implement** phases 1-4 over 4 weeks
6. **Document** thoroughly with examples
7. **Release** as `belgie.ab` v0.1.0

---

## Appendix A: Hash Function Comparison

| Function | Speed | Distribution | Collision Risk | Use Case |
|----------|-------|--------------|----------------|----------|
| MD5 | Fast | Excellent | Very Low | General purpose |
| SHA-256 | Medium | Excellent | Extremely Low | Security-sensitive |
| MurmurHash3 | Very Fast | Excellent | Very Low | High performance |
| FNV-1a | Very Fast | Good | Low | Simple cases |

**Recommendation**: MD5 for v1 (excellent balance), add MurmurHash3 later for high-scale.

---

## Appendix B: Targeting Rules Examples

```python
# Simple equality
targeting_rules = {
    "email_domain": "company.com"
}

# Multiple conditions (AND)
targeting_rules = {
    "scopes": ["ADMIN"],
    "email_verified": True
}

# Percentage rollout
targeting_rules = {
    "rollout_percentage": 25  # Only 25% of users see experiment
}

# Custom attribute
targeting_rules = {
    "custom_attributes.plan": "premium"
}
```

---

## Appendix C: Performance Considerations

**Hash-based assignment** (Proposal A/C):
- Time: O(1) - single hash computation
- Space: O(num_experiments) - in-memory config
- Throughput: ~1M assignments/second on modern CPU

**Database-backed assignment** (Proposal B):
- Time: O(1) - indexed lookup
- Space: O(num_users * num_experiments) - assignment table
- Throughput: ~10K assignments/second (depends on DB)

**Optimization strategies:**
1. Redis cache for experiment config (10x faster DB lookups)
2. In-memory LRU cache for recent assignments (sticky bucketing)
3. Batch event writes (async task queue)
4. Partition events table by date for efficient queries

---

## Appendix D: Integration with Observability

Future integration points for tracing/metrics:

```python
# Tracing (OpenTelemetry)
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def get_variant(...):
    with tracer.start_as_current_span("ab_test.assign") as span:
        span.set_attribute("experiment.name", experiment_name)
        span.set_attribute("user.id", str(user_id))

        variant = await self._assign_variant(...)

        span.set_attribute("experiment.variant", variant)
        return variant

# Metrics (Prometheus)
from prometheus_client import Counter, Histogram

exposure_counter = Counter(
    'ab_test_exposures_total',
    'Total experiment exposures',
    ['experiment', 'variant']
)

assignment_duration = Histogram(
    'ab_test_assignment_duration_seconds',
    'Time to assign variant'
)

# Usage
exposure_counter.labels(experiment=exp_name, variant=variant).inc()
```

---

## Conclusion

The proposed `belgie.ab` module will provide a lightweight, type-safe, and flexible A/B testing solution tightly integrated with belgie's auth and session management. By following a hybrid approach (Proposal C), we enable simple use cases while supporting complex production scenarios.

The design leverages industry best practices (hash-based bucketing, sticky assignments, event tracking) while maintaining belgie's core principles of protocol-based architecture, type safety, and developer ergonomics.
