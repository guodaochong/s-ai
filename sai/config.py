from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # LLM
    zhipuai_api_key: str = Field(default="")

    # PostgreSQL / PostGIS
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "sai"
    postgres_user: str = "postgres"
    postgres_password: str = "changeme"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # Agent Registry
    registry_host: str = "0.0.0.0"
    registry_port: int = 9000
    registry_url: str = "http://localhost:9000"

    # MCP Tool Server URLs
    mcp_gis_url: str = "http://localhost:5001"
    mcp_data_url: str = "http://localhost:5002"
    mcp_knowledge_url: str = "http://localhost:5003"
    mcp_map_url: str = "http://localhost:5004"
    mcp_hydro_url: str = "http://localhost:5005"
    mcp_flood_url: str = "http://localhost:5006"
    mcp_raster_url: str = "http://localhost:5007"

    # General
    log_level: str = "INFO"
    environment: str = "development"


settings = Settings()
