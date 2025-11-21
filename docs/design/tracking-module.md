# Design Document: belgie.tracking - User & Session Analytics

**Author**: Claude
**Date**: 2025-11-21
**Status**: Proposal
**Supersedes**: ab-testing-module.md (A/B testing becomes a sub-module)

---

## Executive Summary

This document proposes `belgie.tracking`, a first-party analytics module for tracking users, sessions, events, and workflows in FastAPI applications. The module integrates deeply with belgie's auth system to automatically capture user context, making it trivial to understand how users move through your application.

**Key Insight**: A/B testing is a specialized case of event tracking. By building a robust tracking foundation first, A/B testing (`belgie.tracking.ab`) becomes a natural extension.

---

## 1. Research Findings

### 1.1 Industry Patterns

**Segment (Analytics CDP)**
- **Naming convention**: "Object Action" (noun + past-tense verb) - "Article Bookmarked", "Purchase Completed"
- **Track with purpose**: Every event should answer a business question
- **Tracking plan**: Document what events mean, why tracked, where triggered
- **Properties**: Extra context for later analysis (user_id, plan_type, amount)

**PostHog (Open Source Product Analytics)**
- Self-hostable, privacy-friendly
- FastAPI integration via middleware
- `posthog.capture(event, properties)` API
- Context management for user sessions
- Exception autocapture

**Mixpanel / Amplitude (Product Analytics)**
- **Funnel analysis**: Track user journey through steps, identify drop-offs
- **Cohorts**: Group users by behavior for analysis
- **User properties**: Persistent attributes (plan, signup_date)
- **Event properties**: Per-event metadata (page_url, button_color)
- Unlimited funnel steps to map entire user journey

**Rails Ahoy (First-Party Analytics)**
- **Visits table**: Session with referrer, location, user_agent
- **Events table**: Actions with name + properties (JSONB)
- Automatic `current_user` attachment
- Simple API: `ahoy.track("event_name", {property: value})`
- New visit after 4 hours of inactivity

**Event Schema Best Practices**
- **Top-down design**: Start with business metrics, derive events
- **Naming**: `category:object_action` format (e.g., `checkout:payment_button_click`)
- **Properties**: `object_adjective` format (e.g., `user_id`, `is_premium`)
- **Documentation**: Maintain tracking plan with event definitions
- **User journey focus**: Map flows from onboarding to advanced usage

### 1.2 Key Architectural Patterns

**Two-Table Model (Visits + Events)**
```
visits         <- Session-level data (user, referrer, duration)
  ↓
events         <- Action-level data (event_name, properties)
```

**Middleware Pattern**
- Intercept all requests/responses
- Automatically capture page views, errors, timing
- Attach user context from auth system

**Decorator Pattern**
- Declaratively mark endpoints for tracking
- Custom properties from function results
- Type-safe event definitions

**Async Processing**
- Non-blocking event recording
- Batch writes for performance
- Background queue (Celery, Redis)

---

## 2. Core Design

### 2.1 Architecture Overview

```
belgie/tracking/
├── core/
│   ├── tracker.py         # Main Tracker class
│   ├── visit.py           # Visit (session) management
│   ├── event.py           # Event models
│   ├── context.py         # Automatic context capture
│   ├── funnel.py          # Funnel/workflow tracking
│   └── settings.py        # Configuration
├── adapters/
│   ├── alchemy.py         # Database storage (default)
│   ├── redis.py           # Redis queue (async processing)
│   └── noop.py            # No-op for testing
├── protocols/
│   └── models.py          # VisitProtocol, EventProtocol
├── middleware/
│   ├── tracking.py        # Automatic request tracking
│   └── performance.py     # Performance monitoring
├── decorators.py          # @track_event, @track_funnel_step
├── dependencies.py        # FastAPI dependencies
└── ab/                    # A/B testing sub-module
    ├── engine.py          # Variant assignment
    ├── analysis.py        # Statistical analysis
    └── dependencies.py    # FastAPI dependencies
```

### 2.2 Data Model

**Visit (Session)**
```python
class VisitProtocol(Protocol):
    """A user session with context."""
    id: UUID
    user_id: UUID | None           # None for anonymous
    session_id: UUID | None        # From auth.session
    started_at: datetime
    ended_at: datetime | None      # Updated on last activity

    # Traffic source
    referrer: str | None
    referrer_domain: str | None
    landing_page: str
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    utm_content: str | None
    utm_term: str | None

    # Device / Browser
    ip_address: str | None
    user_agent: str | None
    browser: str | None
    browser_version: str | None
    os: str | None
    os_version: str | None
    device_type: str | None        # mobile, tablet, desktop

    # Location (optional, from IP)
    country: str | None
    region: str | None
    city: str | None

    # Metrics
    events_count: int = 0
    pageviews_count: int = 0
    duration_seconds: int | None   # Calculated on end
```

**Event**
```python
class EventProtocol(Protocol):
    """A user action or system event."""
    id: UUID
    visit_id: UUID
    user_id: UUID | None           # Denormalized for queries

    # Event identification
    name: str                      # e.g., "checkout:payment_completed"
    category: str | None           # e.g., "checkout"
    action: str | None             # e.g., "payment_completed"

    # Context
    properties: dict               # JSONB - flexible metadata
    timestamp: datetime

    # Request context
    path: str | None
    method: str | None             # GET, POST, etc.
    status_code: int | None
    duration_ms: int | None        # Request duration

    # User context (denormalized for analysis)
    user_email: str | None
    user_scopes: list[str] | None
```

**Key Design Decisions:**

1. **Visit = Session + Context**: Each visit represents a user session with rich metadata
2. **Denormalization**: Store user_id/email in events for fast querying
3. **JSONB properties**: Flexible schema for custom event data
4. **category:action naming**: Structured event names for better organization
5. **Request metrics**: Capture performance data automatically

### 2.3 Core API

**Tracker Class**
```python
from belgie.tracking.core import Tracker
from belgie.tracking.adapters import AlchemyTrackingAdapter

# Initialize
tracker = Tracker(
    adapter=AlchemyTrackingAdapter(visit=Visit, event=Event),
    settings=TrackingSettings()
)

# Track event manually
await tracker.track(
    db=db,
    name="purchase_completed",
    properties={
        "amount": 99.99,
        "currency": "USD",
        "item_count": 3
    },
    user=user,              # Optional, from Depends(auth.user)
    request=request         # Optional, for automatic context
)

# Get or create visit
visit = await tracker.get_or_create_visit(
    db=db,
    user=user,
    session=session,
    request=request
)

# Update visit on activity
await tracker.update_visit_activity(db=db, visit_id=visit.id)
```

**Dependency Injection**
```python
from belgie.tracking.dependencies import get_tracker, get_current_visit

@app.post("/checkout")
async def checkout(
    data: CheckoutData,
    user = Depends(auth.user),
    visit: Visit = Depends(get_current_visit),  # Auto-created
    tracker: Tracker = Depends(get_tracker),
    db = Depends(get_db)
):
    # Process checkout
    result = process_checkout(data)

    # Track completion
    await tracker.track(
        db=db,
        name="checkout:completed",
        properties={
            "amount": result.amount,
            "payment_method": data.payment_method
        }
    )

    return result
```

**Decorator API**
```python
from belgie.tracking.decorators import track_event

@app.post("/signup")
@track_event("user:signup_completed")
async def signup(
    data: SignupData,
    user = Depends(auth.user),
    db = Depends(get_db)
):
    # Handler logic
    result = create_user(data)

    # Event automatically tracked with:
    # - name: "user:signup_completed"
    # - properties: extracted from request/response
    # - user context: from Depends(auth.user)
    # - timing: request duration

    return result

# With custom properties
@app.post("/purchase")
@track_event(
    "purchase:completed",
    properties=lambda result: {
        "amount": result.amount,
        "item_id": result.item_id
    }
)
async def purchase(item: Item, user = Depends(auth.user)):
    result = process_purchase(item)
    return result
```

**Middleware API**
```python
from belgie.tracking.middleware import TrackingMiddleware

app = FastAPI()

# Add tracking middleware
app.add_middleware(
    TrackingMiddleware,
    tracker=tracker,
    auto_track_pageviews=True,      # Track all GET requests as pageviews
    auto_track_errors=True,         # Track 4xx/5xx responses
    track_performance=True,         # Record request duration
    exclude_paths=["/health", "/metrics"]  # Don't track these
)
```

### 2.4 Automatic Context Capture

**Key Principle**: Leverage `auth.user` and `auth.session` to automatically enrich events with user context.

```python
# belgie/tracking/context.py

from fastapi import Request, Depends
from belgie.auth import auth

async def get_tracking_context(
    request: Request,
    user = Depends(auth.user, use_cache=False),      # Optional - None if not auth'd
    session = Depends(auth.session, use_cache=False) # Optional
) -> TrackingContext:
    """Automatically capture tracking context from request."""

    return TrackingContext(
        # User context (from auth)
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        user_scopes=user.scopes if user else None,
        session_id=session.id if session else None,

        # Request context
        path=request.url.path,
        method=request.method,
        query_params=dict(request.query_params),

        # Traffic source (from request)
        referrer=request.headers.get("referer"),
        referrer_domain=extract_domain(request.headers.get("referer")),
        utm_source=request.query_params.get("utm_source"),
        utm_medium=request.query_params.get("utm_medium"),
        utm_campaign=request.query_params.get("utm_campaign"),

        # Device context
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        browser=parse_browser(request.headers.get("user-agent")),
        os=parse_os(request.headers.get("user-agent")),
        device_type=detect_device_type(request.headers.get("user-agent")),

        # Timestamp
        timestamp=datetime.now(timezone.utc)
    )
```

**Usage in Dependencies**
```python
async def get_current_visit(
    db: AsyncSession = Depends(get_db),
    context: TrackingContext = Depends(get_tracking_context),
    tracker: Tracker = Depends(get_tracker)
) -> Visit:
    """Get or create the current visit."""

    # Try to get existing visit from cookie or session
    visit = await tracker.find_current_visit(db, context)

    if not visit or tracker.should_create_new_visit(visit):
        # Create new visit
        visit = await tracker.create_visit(db, context)
    else:
        # Update activity timestamp
        await tracker.update_visit_activity(db, visit.id)

    return visit
```

### 2.5 Funnel / Workflow Tracking

**Funnel Definition**
```python
from belgie.tracking.core import Funnel

# Define a funnel
signup_funnel = Funnel(
    name="user_signup",
    steps=[
        "landing_page_viewed",
        "signup_form_viewed",
        "email_entered",
        "password_entered",
        "signup_completed"
    ],
    max_time_between_steps=timedelta(hours=24)  # Steps must complete in 24h
)

# Use in routes
@app.get("/")
@signup_funnel.track_step("landing_page_viewed")
async def landing_page(user = Depends(auth.user)):
    return {"page": "landing"}

@app.get("/signup")
@signup_funnel.track_step("signup_form_viewed")
async def signup_page(user = Depends(auth.user)):
    return {"page": "signup"}

@app.post("/signup")
@signup_funnel.track_step("signup_completed")
async def complete_signup(data: SignupData, user = Depends(auth.user)):
    result = create_user(data)
    return result
```

**Funnel Analysis**
```python
# Query funnel conversion rates
analysis = await tracker.analyze_funnel(
    db=db,
    funnel=signup_funnel,
    start_date=datetime.now() - timedelta(days=30),
    end_date=datetime.now(),
    segment_by="utm_source"  # Breakdown by traffic source
)

# Returns:
# {
#     "overall": {
#         "landing_page_viewed": 10000,
#         "signup_form_viewed": 5000,     # 50% conversion
#         "email_entered": 3000,          # 60% conversion
#         "password_entered": 2800,       # 93% conversion
#         "signup_completed": 2500        # 89% conversion
#     },
#     "segments": {
#         "google": {...},
#         "facebook": {...}
#     }
# }
```

**Workflow Tracking** (Less rigid than funnels)
```python
from belgie.tracking.core import Workflow

# Define a workflow (order doesn't matter)
onboarding_workflow = Workflow(
    name="user_onboarding",
    actions=[
        "profile_completed",
        "first_project_created",
        "team_invited",
        "payment_method_added"
    ]
)

# Track completion
@app.post("/profile")
@onboarding_workflow.track_action("profile_completed")
async def complete_profile(data: ProfileData, user = Depends(auth.user)):
    update_profile(user, data)
    return {"status": "success"}

# Check workflow progress
progress = await tracker.get_workflow_progress(
    db=db,
    workflow=onboarding_workflow,
    user_id=user.id
)
# Returns: ["profile_completed", "first_project_created"]  # 50% complete
```

---

## 3. Integration with belgie.auth

### 3.1 Automatic User Context

**Key Principle**: When tracking is enabled, user context is automatically captured from `auth.user` without requiring explicit passing.

```python
# Before (manual)
await tracker.track(
    db=db,
    name="feature_used",
    user_id=user.id,
    user_email=user.email,
    user_scopes=user.scopes
)

# After (automatic)
@track_event("feature_used")
async def use_feature(user = Depends(auth.user)):
    # User context automatically captured from Depends(auth.user)
    pass
```

**Implementation**
```python
# belgie/tracking/decorators.py

def track_event(
    name: str,
    properties: Callable | dict | None = None,
    category: str | None = None
):
    """Decorator to track events with automatic user context."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Execute endpoint handler
            result = await func(*args, **kwargs)

            # Extract tracking dependencies from kwargs
            # (FastAPI injects them automatically)
            tracker = kwargs.get("tracker")
            db = kwargs.get("db")
            user = kwargs.get("user")  # From Depends(auth.user)
            visit = kwargs.get("visit")  # From Depends(get_current_visit)
            request = kwargs.get("request")

            if tracker and db:
                # Build event properties
                event_props = {}
                if callable(properties):
                    event_props = properties(result)
                elif isinstance(properties, dict):
                    event_props = properties

                # Track event
                await tracker.track(
                    db=db,
                    name=name,
                    category=category,
                    properties=event_props,
                    user=user,      # Automatically from auth.user
                    visit=visit,    # Automatically from get_current_visit
                    request=request
                )

            return result

        return wrapper
    return decorator
```

### 3.2 Session Correlation

**Visits are tied to auth sessions:**

```python
# When user logs in
@app.post("/auth/callback/google")
async def oauth_callback(...):
    # Auth creates session
    session = await session_manager.create_session(...)

    # Tracking creates/updates visit
    if tracker.enabled:
        visit = await tracker.get_or_create_visit(
            db=db,
            user=user,
            session=session,  # Link to auth session
            request=request
        )

        # Track login event
        await tracker.track(
            db=db,
            name="auth:login_completed",
            properties={"provider": "google"}
        )

    return redirect_response

# When user logs out
@app.post("/auth/signout")
async def signout(...):
    # End visit
    if tracker.enabled:
        await tracker.end_visit(db=db, visit_id=visit.id)

    # Delete session
    await session_manager.delete_session(...)
```

### 3.3 Scope-Based Tracking

**Track events differently based on user scopes:**

```python
from belgie.auth.utils import Scope

@app.get("/admin/dashboard")
@track_event(
    "admin:dashboard_viewed",
    properties=lambda: {"user_scope": "admin"}
)
async def admin_dashboard(
    user = Security(auth.user, scopes=[Scope.ADMIN])
):
    return {"data": "admin_data"}

# Later: analyze admin vs non-admin behavior
events = await tracker.query_events(
    db=db,
    filters={"user_scopes": {"contains": "ADMIN"}},
    group_by="name"
)
```

---

## 4. belgie.tracking.ab - A/B Testing Sub-Module

**Philosophy**: A/B testing is event tracking + variant assignment.

### 4.1 Architecture

```python
# belgie/tracking/ab/engine.py

from belgie.tracking.core import Tracker

class ABEngine:
    """A/B testing engine built on tracking."""

    def __init__(self, tracker: Tracker, adapter: ABAdapter):
        self.tracker = tracker
        self.adapter = adapter

    async def get_variant(
        self,
        db: AsyncSession,
        experiment_name: str,
        user_id: UUID,
        visit: Visit
    ) -> str:
        """Get user's variant and track exposure."""

        # 1. Load experiment
        experiment = await self.adapter.get_experiment(db, experiment_name)

        # 2. Check sticky bucketing
        assignment = await self.adapter.get_assignment(db, experiment.id, user_id)
        if assignment:
            variant = assignment.variant
        else:
            # 3. Hash-based assignment
            variant = self._hash_assign(experiment_name, str(user_id), experiment.variants)

            # 4. Persist assignment
            await self.adapter.create_assignment(db, experiment.id, user_id, variant)

        # 5. Track exposure event using core tracker
        await self.tracker.track(
            db=db,
            name="experiment:exposure",
            category="ab_testing",
            properties={
                "experiment": experiment_name,
                "variant": variant
            },
            visit=visit
        )

        return variant

    async def track_conversion(
        self,
        db: AsyncSession,
        experiment_name: str,
        conversion_name: str,
        user_id: UUID,
        visit: Visit,
        properties: dict | None = None
    ):
        """Track conversion event."""

        # Get user's variant
        assignment = await self.adapter.get_assignment_by_user(
            db, experiment_name, user_id
        )

        if assignment:
            # Track using core tracker
            props = properties or {}
            props.update({
                "experiment": experiment_name,
                "variant": assignment.variant,
                "conversion": conversion_name
            })

            await self.tracker.track(
                db=db,
                name="experiment:conversion",
                category="ab_testing",
                properties=props,
                visit=visit
            )
```

### 4.2 Usage

**Simple A/B Test**
```python
from belgie.tracking.ab import ABEngine, experiment_variant

# Setup
ab_engine = ABEngine(tracker=tracker, adapter=ab_adapter)

# Use in route
@app.get("/landing")
async def landing(
    user = Depends(auth.user),
    visit: Visit = Depends(get_current_visit),
    variant: str = Depends(experiment_variant("landing_redesign")),
    db = Depends(get_db)
):
    # Exposure automatically tracked by experiment_variant dependency

    if variant == "control":
        return render_old_landing()
    else:
        return render_new_landing()

# Track conversion
@app.post("/signup")
async def signup(
    data: SignupData,
    user = Depends(auth.user),
    visit: Visit = Depends(get_current_visit),
    db = Depends(get_db)
):
    result = create_user(data)

    # Track as conversion for experiments
    await ab_engine.track_conversion(
        db=db,
        experiment_name="landing_redesign",
        conversion_name="signup_completed",
        user_id=user.id,
        visit=visit,
        properties={"plan": data.plan}
    )

    return result
```

**Key Insight**: A/B testing events are just regular tracking events with special properties. This means:
- Use same database tables
- Use same analysis tools
- Use same dashboards
- Natural integration with funnels (e.g., "how does variant A affect signup funnel?")

### 4.3 Combined Analysis

**Funnel + A/B Test**
```python
# Analyze signup funnel by experiment variant
analysis = await tracker.analyze_funnel(
    db=db,
    funnel=signup_funnel,
    segment_by="experiment:landing_redesign.variant"
)

# Returns conversion rates for control vs treatment:
# {
#     "control": {
#         "landing_page_viewed": 5000,
#         "signup_form_viewed": 2000,  # 40% conversion
#         "signup_completed": 1000     # 50% conversion
#     },
#     "treatment": {
#         "landing_page_viewed": 5000,
#         "signup_form_viewed": 3000,  # 60% conversion ⬆️
#         "signup_completed": 1800     # 60% conversion ⬆️
#     }
# }
```

---

## 5. Database Schema

### 5.1 Core Tables

```sql
-- Visits (Sessions)
CREATE TABLE tracking_visits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,  -- Nullable for anonymous
    session_id UUID,  -- Reference to auth sessions

    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP,

    -- Traffic source
    referrer TEXT,
    referrer_domain VARCHAR(255),
    landing_page TEXT NOT NULL,
    utm_source VARCHAR(255),
    utm_medium VARCHAR(255),
    utm_campaign VARCHAR(255),
    utm_content VARCHAR(255),
    utm_term VARCHAR(255),

    -- Device / Browser
    ip_address INET,
    user_agent TEXT,
    browser VARCHAR(100),
    browser_version VARCHAR(50),
    os VARCHAR(100),
    os_version VARCHAR(50),
    device_type VARCHAR(20),  -- mobile, tablet, desktop

    -- Location
    country VARCHAR(2),  -- ISO country code
    region VARCHAR(255),
    city VARCHAR(255),

    -- Metrics
    events_count INT DEFAULT 0,
    pageviews_count INT DEFAULT 0,
    duration_seconds INT
);

CREATE INDEX idx_visits_user ON tracking_visits(user_id);
CREATE INDEX idx_visits_session ON tracking_visits(session_id);
CREATE INDEX idx_visits_started ON tracking_visits(started_at);
CREATE INDEX idx_visits_utm_source ON tracking_visits(utm_source);

-- Events
CREATE TABLE tracking_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visit_id UUID REFERENCES tracking_visits(id) ON DELETE CASCADE,
    user_id UUID,  -- Denormalized

    -- Event identification
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    action VARCHAR(100),

    -- Context
    properties JSONB,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Request context
    path TEXT,
    method VARCHAR(10),
    status_code INT,
    duration_ms INT,

    -- User context (denormalized)
    user_email VARCHAR(255),
    user_scopes TEXT[]
);

CREATE INDEX idx_events_visit ON tracking_events(visit_id);
CREATE INDEX idx_events_user ON tracking_events(user_id);
CREATE INDEX idx_events_name ON tracking_events(name);
CREATE INDEX idx_events_category ON tracking_events(category);
CREATE INDEX idx_events_timestamp ON tracking_events(timestamp);
CREATE INDEX idx_events_properties ON tracking_events USING GIN(properties);
```

### 5.2 A/B Testing Tables

```sql
-- Experiments
CREATE TABLE ab_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    variants JSONB NOT NULL,  -- {"control": 0.5, "treatment": 0.5}
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Assignments (Sticky Bucketing)
CREATE TABLE ab_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID REFERENCES ab_experiments(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    variant VARCHAR(100) NOT NULL,
    assigned_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(experiment_id, user_id)
);

CREATE INDEX idx_assignments_user ON ab_assignments(user_id);
CREATE INDEX idx_assignments_experiment ON ab_assignments(experiment_id);
```

**Key Point**: A/B testing doesn't need separate events table - it uses `tracking_events` with special properties!

---

## 6. Configuration

```python
# belgie/tracking/settings.py

from pydantic import BaseSettings

class TrackingSettings(BaseSettings):
    """Configuration for tracking module."""

    # Core settings
    enabled: bool = True
    track_anonymous: bool = True

    # Visit settings
    visit_timeout_seconds: int = 14400  # 4 hours

    # Automatic tracking
    auto_track_pageviews: bool = True
    auto_track_errors: bool = True
    auto_track_performance: bool = True

    # Performance
    batch_size: int = 100
    flush_interval_seconds: int = 5

    # Privacy
    anonymize_ip: bool = False
    hash_ip: bool = False
    exclude_user_agents: list[str] = ["bot", "spider", "crawler"]

    # Storage
    use_async_processing: bool = True
    redis_queue_url: str | None = None

    class Config:
        env_prefix = "BELGIE_TRACKING_"

# Environment variables:
# BELGIE_TRACKING_ENABLED=true
# BELGIE_TRACKING_VISIT_TIMEOUT_SECONDS=14400
# BELGIE_TRACKING_AUTO_TRACK_PAGEVIEWS=true
```

---

## 7. Setup & Integration

### 7.1 Basic Setup

```python
from fastapi import FastAPI
from belgie.auth import Auth
from belgie.tracking import Tracker, TrackingMiddleware
from belgie.tracking.adapters import AlchemyTrackingAdapter
from belgie.tracking.settings import TrackingSettings

# Create FastAPI app
app = FastAPI()

# Setup auth
auth = Auth(...)
app.include_router(auth.router)

# Setup tracking
tracking_adapter = AlchemyTrackingAdapter(
    visit=Visit,
    event=Event
)
tracker = Tracker(
    adapter=tracking_adapter,
    settings=TrackingSettings()
)

# Add tracking middleware
app.add_middleware(
    TrackingMiddleware,
    tracker=tracker,
    auth=auth,  # Pass auth to automatically capture user context
    auto_track_pageviews=True,
    exclude_paths=["/health", "/metrics"]
)

# Make tracker available via dependency injection
from belgie.tracking.dependencies import set_tracker
set_tracker(tracker)
```

### 7.2 With A/B Testing

```python
from belgie.tracking.ab import ABEngine
from belgie.tracking.ab.adapters import AlchemyABAdapter
from belgie.tracking.ab.dependencies import set_ab_engine

# Setup A/B testing (requires tracking)
ab_adapter = AlchemyABAdapter(
    experiment=Experiment,
    assignment=Assignment
)
ab_engine = ABEngine(tracker=tracker, adapter=ab_adapter)
set_ab_engine(ab_engine)

# Now use in routes
from belgie.tracking.ab.dependencies import experiment_variant

@app.get("/feature")
async def feature(
    user = Depends(auth.user),
    variant = Depends(experiment_variant("new_feature"))
):
    if variant == "enabled":
        return new_feature_response()
    else:
        return old_feature_response()
```

---

## 8. API Examples

### 8.1 Manual Event Tracking

```python
from belgie.tracking.dependencies import get_tracker

@app.post("/action")
async def action(
    data: ActionData,
    user = Depends(auth.user),
    tracker: Tracker = Depends(get_tracker),
    db = Depends(get_db)
):
    result = perform_action(data)

    # Manual tracking
    await tracker.track(
        db=db,
        name="action:completed",
        properties={
            "action_type": data.type,
            "result": result.status
        }
    )

    return result
```

### 8.2 Decorator-Based Tracking

```python
from belgie.tracking.decorators import track_event

@app.post("/checkout")
@track_event(
    "checkout:completed",
    properties=lambda result: {
        "amount": result.amount,
        "items": result.item_count
    }
)
async def checkout(
    cart: Cart,
    user = Depends(auth.user),
    db = Depends(get_db)
):
    result = process_checkout(cart)
    # Event automatically tracked with properties extracted from result
    return result
```

### 8.3 Funnel Tracking

```python
from belgie.tracking.core import Funnel

purchase_funnel = Funnel(
    name="purchase_flow",
    steps=[
        "product_viewed",
        "add_to_cart",
        "checkout_started",
        "payment_entered",
        "purchase_completed"
    ]
)

@app.get("/product/{id}")
@purchase_funnel.track_step("product_viewed")
async def view_product(id: str, user = Depends(auth.user)):
    return get_product(id)

@app.post("/cart")
@purchase_funnel.track_step("add_to_cart")
async def add_to_cart(item: Item, user = Depends(auth.user)):
    return add_item(item)

# ... other steps
```

### 8.4 Workflow Progress

```python
from belgie.tracking.core import Workflow
from belgie.tracking.dependencies import get_tracker

onboarding = Workflow(
    name="user_onboarding",
    actions=[
        "profile_completed",
        "team_created",
        "first_resource_added",
        "invite_sent"
    ]
)

@app.get("/onboarding/progress")
async def onboarding_progress(
    user = Depends(auth.user),
    tracker: Tracker = Depends(get_tracker),
    db = Depends(get_db)
):
    progress = await tracker.get_workflow_progress(
        db=db,
        workflow=onboarding,
        user_id=user.id
    )

    return {
        "completed": progress,
        "remaining": [a for a in onboarding.actions if a not in progress],
        "percentage": len(progress) / len(onboarding.actions) * 100
    }
```

### 8.5 Querying Events

```python
from belgie.tracking.dependencies import get_tracker

@app.get("/analytics/events")
async def query_events(
    user = Security(auth.user, scopes=["ADMIN"]),
    tracker: Tracker = Depends(get_tracker),
    db = Depends(get_db)
):
    # Query events with filters
    events = await tracker.query_events(
        db=db,
        filters={
            "name": "purchase:completed",
            "timestamp": {"gte": datetime.now() - timedelta(days=7)}
        },
        group_by="user_id",
        aggregate="count"
    )

    return {"events": events}
```

---

## 9. Privacy & Compliance

### 9.1 PII Handling

```python
# Anonymize IP addresses
settings = TrackingSettings(anonymize_ip=True)
# Stores: 192.168.1.0 instead of 192.168.1.123

# Hash IP addresses
settings = TrackingSettings(hash_ip=True)
# Stores: sha256(ip) for anonymous identification without storing actual IP

# Exclude user agents (bots, etc.)
settings = TrackingSettings(
    exclude_user_agents=["bot", "spider", "crawler", "googlebot"]
)
```

### 9.2 User Data Deletion

```python
@app.delete("/user/data")
async def delete_user_data(
    user = Depends(auth.user),
    tracker: Tracker = Depends(get_tracker),
    db = Depends(get_db)
):
    """GDPR: Delete all user tracking data."""

    # Delete all visits and events
    await tracker.delete_user_data(db=db, user_id=user.id)

    # Also delete A/B test assignments
    await ab_engine.delete_user_assignments(db=db, user_id=user.id)

    return {"status": "deleted"}
```

### 9.3 Opt-Out

```python
@app.post("/tracking/opt-out")
async def opt_out_tracking(
    user = Depends(auth.user),
    db = Depends(get_db)
):
    """Allow users to opt out of tracking."""

    # Store preference in user model
    await update_user(db, user.id, tracking_enabled=False)

    return {"status": "opted_out"}

# In tracking middleware
class TrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        user = await get_user(request)

        if user and not user.tracking_enabled:
            # Skip tracking
            return await call_next(request)

        # Normal tracking
        ...
```

---

## 10. Performance Considerations

### 10.1 Async Processing

```python
# Use Redis queue for async event processing
from belgie.tracking.adapters import RedisQueueAdapter

tracker = Tracker(
    adapter=AlchemyTrackingAdapter(...),
    queue_adapter=RedisQueueAdapter(redis_url="redis://localhost"),
    settings=TrackingSettings(use_async_processing=True)
)

# Events are queued, not blocking requests
await tracker.track(...)  # Returns immediately

# Background worker processes queue
# $ python -m belgie.tracking.worker
```

### 10.2 Batching

```python
# Batch writes for performance
settings = TrackingSettings(
    batch_size=100,           # Write 100 events at once
    flush_interval_seconds=5  # Flush every 5 seconds
)

# Internal buffer accumulates events, flushes periodically
```

### 10.3 Indexing

```sql
-- Essential indexes for query performance
CREATE INDEX idx_events_name ON tracking_events(name);
CREATE INDEX idx_events_timestamp ON tracking_events(timestamp);
CREATE INDEX idx_events_user_timestamp ON tracking_events(user_id, timestamp);

-- For funnel queries
CREATE INDEX idx_events_visit_timestamp ON tracking_events(visit_id, timestamp);

-- For property queries
CREATE INDEX idx_events_properties ON tracking_events USING GIN(properties);
```

---

## 11. Comparison: Tracking First vs A/B Testing First

### Previous Approach (A/B Testing First)
- ❌ Limited to A/B test events
- ❌ Can't track general user behavior
- ❌ Separate system for product analytics
- ❌ No funnel analysis
- ❌ No user journey tracking

### New Approach (Tracking First)
- ✅ Track all user behavior
- ✅ A/B testing is specialized tracking
- ✅ Unified analytics system
- ✅ Built-in funnel analysis
- ✅ Complete user journey tracking
- ✅ A/B tests integrate with funnels
- ✅ Reuse same tables, same queries, same dashboards

---

## 12. Implementation Roadmap

### Phase 1: Core Tracking (Week 1-2)
- [ ] `tracking/core/tracker.py` - Main Tracker class
- [ ] `tracking/core/visit.py` - Visit management
- [ ] `tracking/core/event.py` - Event models
- [ ] `tracking/protocols/models.py` - Protocols
- [ ] `tracking/adapters/alchemy.py` - Database adapter
- [ ] `tracking/dependencies.py` - FastAPI dependencies
- [ ] `tracking/context.py` - Automatic context capture
- [ ] Database migrations
- [ ] Tests

### Phase 2: Automatic Tracking (Week 2-3)
- [ ] `tracking/middleware/tracking.py` - Request tracking
- [ ] `tracking/decorators.py` - @track_event decorator
- [ ] Integration with auth.user
- [ ] Pageview tracking
- [ ] Error tracking
- [ ] Performance metrics
- [ ] Tests

### Phase 3: Funnels & Workflows (Week 3-4)
- [ ] `tracking/core/funnel.py` - Funnel tracking
- [ ] `tracking/core/workflow.py` - Workflow progress
- [ ] Funnel analysis queries
- [ ] Conversion rate calculations
- [ ] Drop-off analysis
- [ ] Tests

### Phase 4: A/B Testing (Week 4-5)
- [ ] `tracking/ab/engine.py` - Variant assignment
- [ ] `tracking/ab/adapters/alchemy.py` - AB adapter
- [ ] `tracking/ab/dependencies.py` - FastAPI dependencies
- [ ] Hash-based bucketing
- [ ] Sticky assignments
- [ ] Exposure tracking via core tracker
- [ ] Conversion tracking
- [ ] Tests

### Phase 5: Analysis & Optimization (Week 5-6)
- [ ] Query optimization
- [ ] Async processing with Redis
- [ ] Batching & buffering
- [ ] Statistical analysis utilities
- [ ] Export utilities
- [ ] Documentation
- [ ] Example applications

---

## 13. Success Metrics

1. **Simplicity**: Setup tracking in < 10 minutes
2. **Automatic**: 80% of tracking happens automatically via middleware
3. **Performance**: < 5ms overhead per tracked request
4. **Adoption**: Developers prefer belgie.tracking over external tools
5. **Integration**: Seamless with auth - zero manual user context passing

---

## 14. Open Questions

1. **IP Geolocation**: Include built-in geolocation or require external service?
   - **Recommendation**: External service (MaxMind, IP2Location) via adapter pattern

2. **User-Agent Parsing**: Built-in or external library?
   - **Recommendation**: Use `user-agents` Python library

3. **Real-time Dashboards**: Include or external?
   - **Recommendation**: Phase 2 feature - basic JSON API, external tools for viz

4. **Data Retention**: Auto-delete old events?
   - **Recommendation**: Configurable retention policy (default: keep forever)

5. **Export Format**: What formats for analysis?
   - **Recommendation**: JSON, CSV, Parquet (for data warehouses)

---

## 15. Conclusion

By building `belgie.tracking` as the foundation and `belgie.tracking.ab` as a specialized extension, we create a comprehensive analytics solution that:

1. **Tracks user journeys** through your application
2. **Automatically captures context** from auth system
3. **Analyzes funnels and workflows** to understand conversion
4. **Runs A/B tests** as a natural extension of event tracking
5. **Maintains privacy** with built-in anonymization
6. **Scales efficiently** with async processing and batching

The key architectural insight is that **A/B testing is event tracking with variant assignment**. By recognizing this, we avoid duplicating infrastructure and create a more powerful, unified system.

Next steps: Prototype Phase 1 (core tracking) to validate API design and integration patterns.
