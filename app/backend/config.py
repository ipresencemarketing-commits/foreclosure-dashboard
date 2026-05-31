from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    database_url: str

    # Supabase (auth)
    supabase_url: str
    supabase_anon_key: str
    supabase_jwt_secret: str

    # Stripe
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_price_starter: str   # price_xxx from Stripe dashboard
    stripe_price_pro: str

    # App
    app_url: str = "http://localhost:3000"
    environment: str = "development"

    class Config:
        env_file = ".env"

settings = Settings()
