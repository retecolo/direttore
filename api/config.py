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
    proxmox_enabled: bool = True # Set to false to entirely hide proxmox features

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

    # ContainerLab
    # Set CLAB_MODE to enable the ContainerLab page. Leave empty to hide it.
    # Supported values: local | ssh | rest
    clab_mode: str = ""              # leave empty = feature hidden in UI
    clab_binary: str = "clab"        # path/binary name for local mode
    clab_topo_dir: str = "/opt/direttore/topologies"  # topology .yml storage dir

    # SSH backend (clab_mode=ssh)
    clab_ssh_host: str = ""
    clab_ssh_port: int = 22
    clab_ssh_user: str = "root"
    clab_ssh_key_path: str = ""      # path to SSH private key file
    clab_ssh_password: str = ""      # password fallback (prefer key)
    clab_ssh_pool_size: int = 4       # max concurrent SSH connections for ssh mode

    # REST backend — clab-api-server (clab_mode=rest)
    # https://github.com/srl-labs/clab-api-server
    clab_api_url: str = ""           # e.g. https://clab-host:8080
    clab_api_token: str = ""         # Bearer token (if api-server uses token auth)
    clab_api_username: str = ""      # HTTP Basic username (alternative to token)
    clab_api_password: str = ""      # HTTP Basic password
    clab_api_verify_ssl: bool = True

    # Topology Git backing (optional — works alongside any CLAB_MODE)
    # Stores topology .yml files in a Git repo for history / rollback.
    clab_topo_git_repo: str = ""          # HTTPS clone URL
    clab_topo_git_branch: str = "main"
    clab_topo_git_auth_token: str = ""    # PAT for HTTPS push
    clab_topo_git_local_path: str = "/opt/direttore/clab-topologies"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


settings = Settings()
