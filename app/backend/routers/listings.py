from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text
from typing import Optional
from database import get_db
from models import Listing, User, UserCounty, SavedListing
from auth import get_current_user
import uuid

router = APIRouter(prefix="/listings", tags=["listings"])

def listing_to_dict(l: Listing) -> dict:
    return {
        "id":                   l.id,
        "address":              l.address,
        "city":                 l.city,
        "county":               l.county,
        "state":                l.state,
        "zip":                  l.zip,
        "property_type":        l.property_type,
        "stage":                l.stage,
        "sale_date":            l.sale_date.isoformat() if l.sale_date else None,
        "sale_time":            l.sale_time,
        "sale_location":        l.sale_location,
        "days_until_sale":      l.days_until_sale,
        "asking_price":         float(l.asking_price) if l.asking_price else None,
        "assessed_value":       float(l.assessed_value) if l.assessed_value else None,
        "rough_equity_est":     float(l.rough_equity_est) if l.rough_equity_est else None,
        "est_profit_potential": float(l.est_profit_potential) if l.est_profit_potential else None,
        "original_principal":   float(l.original_principal) if l.original_principal else None,
        "beds_baths_sqft":      l.beds_baths_sqft,
        "year_built":           l.year_built,
        "lot_size":             l.lot_size,
        "last_sold_date":       l.last_sold_date.isoformat() if l.last_sold_date else None,
        "last_sold_price":      float(l.last_sold_price) if l.last_sold_price else None,
        "owner_name":           l.owner_name,
        "owner_mailing_address":l.owner_mailing_address,
        "owner_mailing_differs":l.owner_mailing_differs,
        "lender":               l.lender,
        "trustee":              l.trustee,
        "notice_date":          l.notice_date.isoformat() if l.notice_date else None,
        "notice_text":          l.notice_text,
        "source":               l.source,
        "source_url":           l.source_url,
        "first_seen":           l.first_seen.isoformat() if l.first_seen else None,
        "is_new":               l.is_new,
        "investment_priority":  l.investment_priority,
    }


@router.get("/")
async def get_listings(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    county: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    days_until_sale_max: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """
    Return listings filtered by the subscriber's selected counties.
    If county param is provided, filter to that specific county.
    """
    # Load user's subscribed counties
    result = await db.execute(
        select(UserCounty.county).where(UserCounty.user_id == current_user["id"])
    )
    subscribed = [r[0] for r in result.fetchall()]

    if not subscribed:
        return {"listings": [], "total": 0, "page": page, "page_size": page_size}

    # Build query
    filters = [Listing.county.in_(subscribed)]
    if county:
        if county not in subscribed:
            raise HTTPException(status_code=403, detail="Not subscribed to that county")
        filters.append(Listing.county == county)
    if stage:
        filters.append(Listing.stage == stage)
    if priority:
        filters.append(Listing.investment_priority == priority)
    if days_until_sale_max is not None:
        filters.append(Listing.days_until_sale <= days_until_sale_max)

    # Only show upcoming sales (not past)
    filters.append(text("(sale_date IS NULL OR sale_date >= CURRENT_DATE)"))

    count_q = await db.execute(
        select(Listing.id).where(and_(*filters))
    )
    total = len(count_q.fetchall())

    q = await db.execute(
        select(Listing)
        .where(and_(*filters))
        .order_by(Listing.sale_date.asc().nullslast(), Listing.investment_priority.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    listings = q.scalars().all()

    return {
        "listings":  [listing_to_dict(l) for l in listings],
        "total":     total,
        "page":      page,
        "page_size": page_size,
    }


@router.get("/{listing_id}")
async def get_listing(
    listing_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    # Verify user is subscribed to this county
    county_check = await db.execute(
        select(UserCounty).where(
            and_(UserCounty.user_id == current_user["id"], UserCounty.county == listing.county)
        )
    )
    if not county_check.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not subscribed to this county")

    return listing_to_dict(listing)


@router.post("/{listing_id}/save")
async def save_listing(
    listing_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    saved = SavedListing(user_id=current_user["id"], listing_id=listing_id)
    db.add(saved)
    await db.commit()
    return {"saved": True}


@router.delete("/{listing_id}/save")
async def unsave_listing(
    listing_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SavedListing).where(
            and_(SavedListing.user_id == current_user["id"], SavedListing.listing_id == listing_id)
        )
    )
    saved = result.scalar_one_or_none()
    if saved:
        await db.delete(saved)
        await db.commit()
    return {"saved": False}


@router.get("/saved/all")
async def get_saved_listings(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Listing)
        .join(SavedListing, SavedListing.listing_id == Listing.id)
        .where(SavedListing.user_id == current_user["id"])
        .order_by(SavedListing.saved_at.desc())
    )
    listings = result.scalars().all()
    return {"listings": [listing_to_dict(l) for l in listings]}
