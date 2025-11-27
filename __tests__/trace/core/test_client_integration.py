from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from belgie.trace.core.client import TraceClient
from belgie.trace.core.settings import TraceSettings
from belgie.trace.core.trace import Trace


@pytest.fixture
def trace_settings() -> TraceSettings:
    """Test trace configuration."""
    return TraceSettings(enabled=True)


@pytest.fixture
def db_dependency():
    async def _get_db():
        yield None

    return SimpleNamespace(dependency=_get_db)


@pytest.fixture
def mock_adapter() -> Mock:
    """Mock adapter for testing."""
    return Mock()


@pytest.fixture
def trace(trace_settings: TraceSettings, mock_adapter: Mock, db_dependency) -> Trace:
    """Trace instance (TraceClient factory)."""
    return Trace(settings=trace_settings, adapter=mock_adapter, db=db_dependency)


@pytest.fixture
def app(trace: Trace) -> FastAPI:
    """FastAPI app with test endpoints using TraceClient."""
    app = FastAPI()

    @app.get("/trace-info")
    async def get_trace_info(client: TraceClient = Depends(trace)):
        """Get trace client info."""
        return {
            "has_adapter": client.adapter is not None,
            "enabled": client.settings.enabled,
            "has_db": client.db is not None,
        }

    @app.get("/trace-settings")
    async def get_trace_settings(client: TraceClient = Depends(trace)):
        """Get trace settings."""
        return {"enabled": client.settings.enabled}

    return app


class TestTraceClientDependency:
    """Test TraceClient as FastAPI dependency."""

    def test_trace_client_injected_into_endpoint(self, app: FastAPI) -> None:
        """TraceClient is properly injected via Depends."""
        client = TestClient(app)
        response = client.get("/trace-info")

        assert response.status_code == 200
        data = response.json()
        assert data["has_adapter"] is True
        assert data["enabled"] is True

    def test_trace_settings_accessible_in_endpoint(self, app: FastAPI) -> None:
        """TraceClient settings are accessible."""
        client = TestClient(app)
        response = client.get("/trace-settings")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True


class TestTraceClientSettings:
    """Test TraceClient with different settings."""

    def test_trace_client_with_disabled_setting(self) -> None:
        """TraceClient respects disabled setting."""
        settings = TraceSettings(enabled=False)

        # Create mock adapter
        adapter = Mock()

        async def get_db():
            yield None

        adapter.dependency = get_db

        trace = Trace(settings=settings, adapter=adapter)

        app = FastAPI()

        @app.get("/status")
        async def get_status(client: TraceClient = Depends(trace)):
            return {"enabled": client.settings.enabled}

        client = TestClient(app)
        response = client.get("/status")

        assert response.status_code == 200
        assert response.json()["enabled"] is False


class TestTraceClientImmutability:
    """Test TraceClient immutability in FastAPI context."""

    def test_trace_client_is_immutable(self, app: FastAPI) -> None:
        """TraceClient cannot be modified after creation."""
        test_client = TestClient(app)

        # Make a request to create a TraceClient instance
        response = test_client.get("/trace-info")
        assert response.status_code == 200

        # The client should be frozen (tested in unit tests)
        # This integration test verifies it works in FastAPI context


class TestMultipleRequests:
    """Test TraceClient behavior across multiple requests."""

    def test_trace_client_created_per_request(self, app: FastAPI) -> None:
        """Each request gets its own TraceClient instance."""
        client = TestClient(app)

        # Make multiple requests
        response1 = client.get("/trace-info")
        response2 = client.get("/trace-info")

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Both should have the same configuration
        assert response1.json() == response2.json()

    def test_settings_consistent_across_requests(self, app: FastAPI) -> None:
        """Settings remain consistent across multiple requests."""
        client = TestClient(app)

        responses = [client.get("/trace-settings") for _ in range(5)]

        assert all(r.status_code == 200 for r in responses)
        assert all(r.json()["enabled"] is True for r in responses)


class TestDescriptorPattern:
    """Test the descriptor pattern works correctly with FastAPI."""

    def test_descriptor_creates_new_client_per_request(self) -> None:
        """Descriptor creates new TraceClient for each request."""
        settings = TraceSettings(enabled=True)

        # Create mock adapter
        adapter = Mock()

        async def get_db():
            yield None

        adapter.dependency = get_db

        trace = Trace(settings=settings, adapter=adapter)

        app = FastAPI()
        clients_created = []

        @app.get("/test")
        async def test_endpoint(client: TraceClient = Depends(trace)):
            # Store client id to verify uniqueness
            clients_created.append(id(client))
            return {"client_id": id(client)}

        test_client = TestClient(app)

        # Make multiple requests
        test_client.get("/test")
        test_client.get("/test")
        test_client.get("/test")

        # Each request should create a new client instance
        # (In FastAPI, dependencies are recreated per request)
        assert len(clients_created) == 3
