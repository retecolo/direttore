# Hardware / Unimus / Git config settings added to existing Settings class.
# These are appended — do not replace config.py; add the fields below.

"""Configuration settings loaded from environment / .env file."""


from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Proxmox
    proxmox_host: str = "192.168.1.100"
    proxmox_user: str = "root@pam"
    proxmox_password: str = "changeme"
    proxmox_verify_ssl: bool = False
    proxmox_mock: bool = False  # Set to true for dev without a real Proxmox host

    # NetBox
    netbox_url: str = "http://localhost:8000"
    netbox_token: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./direttore.db"

    # CORS — comma-separated allowed origins
    api_cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Unimus (Pro)
    unimus_url: str = ""          # e.g. https://unimus.example.com
    unimus_token: str = ""        # API token from Unimus → Settings → API access

    # Git config repository
    git_config_repo: str = ""         # HTTPS or SSH clone URL
    git_config_branch: str = "main"   # branch to read/write configs on
    git_config_auth_token: str = ""   # GitHub/GitLab PAT for HTTPS push
    git_config_local_path: str = "/opt/direttore/config-repo"
    # Filesystem path used as the author identity in commits
    git_config_author_name: str = "Direttore"
    git_config_author_email: str = "direttore@localhost"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


settings = Settings()
