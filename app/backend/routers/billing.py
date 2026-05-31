import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models import User
from auth import get_current_user
from config import settings
from routers.users import get_or_create_user

stripe.api_key = settings.stripe_secret_key

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_PRICES = {
    "starter": settings.stripe_price_starter,
    "pro":     settings.stripe_price_pro,
}


@router.post("/checkout/{plan}")
async def create_checkout_session(
    plan: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail="Invalid plan")

    user = await get_or_create_user(current_user, db)

    # Create Stripe customer if needed
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email, metadata={"user_id": str(user.id)})
        user.stripe_customer_id = customer.id
        await db.commit()

    session = stripe.checkout.Session.create(
        customer=user.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": PLAN_PRICES[plan], "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.app_url}/dashboard?subscribed=true",
        cancel_url=f"{settings.app_url}/pricing",
        metadata={"user_id": str(user.id), "plan": plan},
    )

    return {"checkout_url": session.url}


@router.post("/portal")
async def create_billing_portal(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await get_or_create_user(current_user, db)
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{settings.app_url}/dashboard",
    )
    return {"portal_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    data = event["data"]["object"]

    if event["type"] == "checkout.session.completed":
        user_id = data["metadata"]["user_id"]
        plan    = data["metadata"]["plan"]
        sub_id  = data["subscription"]
        result  = await db.execute(select(User).where(User.id == user_id))
        user    = result.scalar_one_or_none()
        if user:
            user.plan           = plan
            user.plan_status    = "active"
            user.stripe_sub_id  = sub_id
            await db.commit()

    elif event["type"] == "customer.subscription.updated":
        sub     = stripe.Subscription.retrieve(data["id"])
        result  = await db.execute(select(User).where(User.stripe_sub_id == data["id"]))
        user    = result.scalar_one_or_none()
        if user:
            user.plan_status = sub.status
            await db.commit()

    elif event["type"] == "customer.subscription.deleted":
        result = await db.execute(select(User).where(User.stripe_sub_id == data["id"]))
        user   = result.scalar_one_or_none()
        if user:
            user.plan        = "free"
            user.plan_status = "canceled"
            user.stripe_sub_id = None
            await db.commit()

    return {"received": True}
