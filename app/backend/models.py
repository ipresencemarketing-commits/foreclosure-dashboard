from sqlalchemy import Column, Text, Numeric, Integer, Boolean, Date, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from database import Base
import uuid

class Listing(Base):
    __tablename__ = "listings"

    id                  = Column(Text, primary_key=True)
    source              = Column(Text, nullable=False)
    source_url          = Column(Text)
    address             = Column(Text, nullable=False)
    city                = Column(Text)
    county              = Column(Text)
    state               = Column(Text, default="VA")
    zip                 = Column(Text)
    property_type       = Column(Text, default="single-family")
    stage               = Column(Text)
    sale_date           = Column(Date)
    sale_time           = Column(Text)
    sale_location       = Column(Text)
    days_until_sale     = Column(Integer)
    asking_price        = Column(Numeric(12, 2))
    assessed_value      = Column(Numeric(12, 2))
    original_principal  = Column(Numeric(12, 2))
    rough_equity_est    = Column(Numeric(12, 2))
    est_profit_potential= Column(Numeric(12, 2))
    deposit             = Column(Text)
    beds_baths_sqft     = Column(Text)
    year_built          = Column(Integer)
    lot_size            = Column(Text)
    last_sold_date      = Column(Date)
    last_sold_price     = Column(Numeric(12, 2))
    years_since_last_sale = Column(Integer)
    owner_name          = Column(Text)
    owner_mailing_address = Column(Text)
    owner_mailing_differs = Column(Boolean)
    lender              = Column(Text)
    trustee             = Column(Text)
    notice_date         = Column(Date)
    notice_text         = Column(Text)
    deed_of_trust_date  = Column(Date)
    days_in_foreclosure = Column(Integer)
    first_seen          = Column(Date, server_default=func.current_date())
    last_updated        = Column(DateTime(timezone=True), server_default=func.now())
    is_new              = Column(Boolean, default=True)
    investment_priority = Column(Text)
    estimated_phone     = Column(Text)
    estimated_email     = Column(Text)
    notes               = Column(Text)


class User(Base):
    __tablename__ = "users"

    id                  = Column(UUID(as_uuid=True), primary_key=True)
    email               = Column(Text, unique=True, nullable=False)
    full_name           = Column(Text)
    phone               = Column(Text)
    stripe_customer_id  = Column(Text, unique=True)
    stripe_sub_id       = Column(Text, unique=True)
    plan                = Column(Text, default="free")
    plan_status         = Column(Text, default="inactive")
    plan_started_at     = Column(DateTime(timezone=True))
    plan_ends_at        = Column(DateTime(timezone=True))
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), server_default=func.now())


class UserCounty(Base):
    __tablename__ = "user_counties"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    county      = Column(Text, nullable=False)
    state       = Column(Text, default="VA")
    added_at    = Column(DateTime(timezone=True), server_default=func.now())


class SavedListing(Base):
    __tablename__ = "saved_listings"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    listing_id  = Column(Text, ForeignKey("listings.id", ondelete="CASCADE"))
    saved_at    = Column(DateTime(timezone=True), server_default=func.now())
    notes       = Column(Text)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at      = Column(DateTime(timezone=True), server_default=func.now())
    finished_at     = Column(DateTime(timezone=True))
    status          = Column(Text, default="running")
    listings_added  = Column(Integer, default=0)
    listings_updated= Column(Integer, default=0)
    error_message   = Column(Text)
    source_counts   = Column(JSON)
