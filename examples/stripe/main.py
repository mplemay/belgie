from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

import stripe
from belgie_stripe import Stripe, StripePlan, StripeSubscription
from brussels.base import DataclassBase
from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from belgie import Belgie, BelgieClient, BelgieSettings, CookieSettings, URLSettings
from belgie.alchemy import BelgieAdapter, StripeAdapter
from examples.stripe.models import Account, Individual, OAuthAccount, OAuthState, Session, Subscription

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

DB_PATH = "./belgie_stripe_example.db"


class StripeExampleSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_STRIPE_EXAMPLE_",
        env_file=".env",
        extra="ignore",
    )

    secret_key: str = "sk_test_change_me"  # noqa: S105
    webhook_secret: str = "whsec_change_me"  # noqa: S105
    pro_price_id: str = "price_pro_monthly"
    pro_annual_price_id: str = "price_pro_annual"
    belgie_secret: str = "change-me"  # noqa: S105
    belgie_base_url: str = "http://localhost:8000"


class HomeResponse(BaseModel):
    message: str
    login: str
    me: str
    subscription_upgrade: str
    subscription_list: str
    subscription_cancel: str
    subscription_restore: str
    subscription_billing_portal: str
    stripe_webhook: str
    signout: str


class MeResponse(BaseModel):
    individual_id: str
    email: str
    name: str | None
    stripe_customer_id: str | None
    session_id: str


engine = create_async_engine(
    URL.create("sqlite+aiosqlite", database=DB_PATH),
    echo=True,
)
session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_maker() as session:
        yield session


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(DataclassBase.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Belgie Stripe Example", lifespan=lifespan)

stripe_settings = StripeExampleSettings()
belgie_settings = BelgieSettings(
    secret=stripe_settings.belgie_secret,
    base_url=stripe_settings.belgie_base_url,
    cookie=CookieSettings(
        secure=False,
        http_only=True,
        same_site="lax",
    ),
    urls=URLSettings(
        signin_redirect="/me",
        signout_redirect="/",
    ),
)

belgie = Belgie(
    settings=belgie_settings,
    adapter=BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,
    ),
    database=get_db,
)
stripe_adapter = StripeAdapter(subscription=Subscription)
belgie.add_plugin(
    Stripe(
        stripe=stripe.StripeClient(
            stripe_settings.secret_key,
            http_client=stripe.HTTPXClient(),
        ),
        stripe_webhook_secret=stripe_settings.webhook_secret,
        subscription=StripeSubscription(
            adapter=stripe_adapter,
            plans=[
                StripePlan(
                    name="pro",
                    price_id=stripe_settings.pro_price_id,
                    annual_price_id=stripe_settings.pro_annual_price_id,
                ),
            ],
        ),
    ),
)
belgie_client_dependency = Annotated[BelgieClient, Depends(belgie)]
current_individual_dependency = Annotated[Individual, Depends(belgie.individual)]
current_session_dependency = Annotated[Session, Depends(belgie.session)]

app.include_router(belgie.router)


@app.get("/")
async def home() -> HomeResponse:
    return HomeResponse(
        message="belgie stripe example",
        login="/login?email=dev@example.com&name=Stripe%20Tester&return_to=/me",
        me="/me",
        subscription_upgrade="/auth/subscription/upgrade",
        subscription_list="/auth/subscription/list",
        subscription_cancel="/auth/subscription/cancel",
        subscription_restore="/auth/subscription/restore",
        subscription_billing_portal="/auth/subscription/billing-portal",
        stripe_webhook="/auth/stripe/webhook",
        signout="/auth/signout",
    )


@app.get("/login")
async def login(
    request: Request,
    client: belgie_client_dependency,
    email: Annotated[str, Query()] = "dev@example.com",
    name: Annotated[str | None, Query()] = "Stripe Tester",
    return_to: Annotated[str, Query()] = "/",
) -> RedirectResponse:
    _user, session = await client.sign_up(
        email=email,
        name=name,
        request=request,
        email_verified_at=datetime.now(UTC),
    )
    response = RedirectResponse(url=return_to, status_code=status.HTTP_302_FOUND)
    return client.create_session_cookie(session, response)


@app.get("/me")
async def me(
    user: current_individual_dependency,
    session: current_session_dependency,
) -> MeResponse:
    return MeResponse(
        individual_id=str(user.id),
        email=user.email,
        name=user.name,
        stripe_customer_id=user.stripe_customer_id,
        session_id=str(session.id),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
