from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_
from pydantic import BaseModel
from typing import List
from database import get_db
from models import User, UserCounty
from auth import get_current_user
import uuid

router = APIRouter(prefix="/users", tags=["users"])

VIRGINIA_COUNTIES = [
    "Accomack", "Albemarle", "Alleghany", "Amelia", "Amherst", "Appomattox",
    "Arlington", "Augusta", "Bath", "Bedford", "Bland", "Botetourt", "Brunswick",
    "Buchanan", "Buckingham", "Campbell", "Caroline", "Carroll", "Charles City",
    "Charlotte", "Chesterfield", "Clarke", "Craig", "Culpeper", "Cumberland",
    "Dickenson", "Dinwiddie", "Essex", "Fairfax", "Fauquier", "Floyd", "Fluvanna",
    "Franklin", "Frederick", "Giles", "Gloucester", "Goochland", "Grayson",
    "Greene", "Greensville", "Halifax", "Hanover", "Henrico", "Henry", "Highland",
    "Isle of Wight", "James City", "King and Queen", "King George", "King William",
    "Lancaster", "Lee", "Loudoun", "Louisa", "Lunenburg", "Madison", "Mathews",
    "Mecklenburg", "Middlesex", "Montgomery", "Nelson", "New Kent", "Northampton",
    "Northumberland", "Nottoway", "Orange", "Page", "Patrick", "Pittsylvania",
    "Powhatan", "Prince Edward", "Prince George", "Prince William", "Pulaski",
    "Rappahannock", "Richmond", "Roanoke", "Rockbridge", "Rockingham", "Russell",
    "Scott", "Shenandoah", "Smyth", "Southampton", "Spotsylvania", "Stafford",
    "Surry", "Sussex", "Tazewell", "Warren", "Washington", "Westmoreland",
    "Wise", "Wythe", "York",
    # Independent Cities
    "Alexandria City", "Bristol City", "Buena Vista City", "Charlottesville City",
    "Chesapeake City", "Colonial Heights City", "Covington City", "Danville City",
    "Emporia City", "Fairfax City", "Falls Church City", "Franklin City",
    "Fredericksburg City", "Galax City", "Hampton City", "Harrisonburg City",
    "Hopewell City", "Lexington City", "Lynchburg City", "Manassas City",
    "Manassas Park City", "Martinsville City", "Newport News City", "Norfolk City",
    "Norton City", "Petersburg City", "Poquoson City", "Portsmouth City",
    "Radford City", "Richmond City", "Roanoke City", "Salem City",
    "Staunton City", "Suffolk City", "Virginia Beach City", "Waynesboro City",
    "Williamsburg City", "Winchester City",
]

class CountyUpdate(BaseModel):
    counties: List[str]

class ProfileUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None


async def get_or_create_user(current_user: dict, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one_or_none()
    if not user:
        user = User(id=current_user["id"], email=current_user["email"])
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


@router.get("/me")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await get_or_create_user(current_user, db)

    county_result = await db.execute(
        select(UserCounty.county).where(UserCounty.user_id == user.id)
    )
    counties = [r[0] for r in county_result.fetchall()]

    return {
        "id":               str(user.id),
        "email":            user.email,
        "full_name":        user.full_name,
        "phone":            user.phone,
        "plan":             user.plan,
        "plan_status":      user.plan_status,
        "plan_ends_at":     user.plan_ends_at.isoformat() if user.plan_ends_at else None,
        "counties":         counties,
        "county_limit":     5 if user.plan == "starter" else (None if user.plan == "pro" else 1),
    }


@router.patch("/me")
async def update_profile(
    body: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await get_or_create_user(current_user, db)
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.phone is not None:
        user.phone = body.phone
    await db.commit()
    return {"updated": True}


@router.put("/me/counties")
async def set_counties(
    body: CountyUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await get_or_create_user(current_user, db)

    # Validate county names
    invalid = [c for c in body.counties if c not in VIRGINIA_COUNTIES]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown counties: {invalid}")

    # Enforce plan limits
    limit = 1 if user.plan == "free" else (5 if user.plan == "starter" else None)
    if limit and len(body.counties) > limit:
        raise HTTPException(
            status_code=403,
            detail=f"Your {user.plan} plan allows up to {limit} counties. Upgrade to add more."
        )

    # Replace all counties
    await db.execute(delete(UserCounty).where(UserCounty.user_id == user.id))
    for county in body.counties:
        db.add(UserCounty(user_id=user.id, county=county))
    await db.commit()

    return {"counties": body.counties}


@router.get("/counties/available")
async def get_available_counties():
    """All Virginia counties and independent cities."""
    return {"counties": VIRGINIA_COUNTIES}
