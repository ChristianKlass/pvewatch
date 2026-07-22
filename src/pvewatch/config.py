from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Proxmox connection
    pve_host: str
    pve_port: int = 8006
    pve_node: str
    pve_token_id: str
    pve_token_secret: str
    pve_verify_ssl: bool = False

    # Email
    alert_email_smtp_host: str = ""
    alert_email_smtp_port: int = 587
    alert_email_smtp_user: str = ""
    alert_email_smtp_pass: str = ""
    alert_email_to: str = ""
    alert_email_from: str = ""

    # Discord
    alert_discord_webhook: str = ""

    # Schedule
    poll_interval_minutes: int = 15
    digest_day: str = "sunday"
    digest_hour: int = 9

    # Thresholds
    storage_alert_threshold: int = 85

    # Heartbeat
    heartbeat_url: str = ""

    # Web UI
    web_ui_enabled: bool = True
    web_ui_port: int = 8080
    web_ui_username: str = ""
    web_ui_password: str = ""

    # Data
    data_path: str = "/data"
    history_days: int = 30
    database_url: str = ""

    @field_validator("digest_day")
    @classmethod
    def validate_digest_day(cls, v: str) -> str:
        days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
        if v.lower() not in days:
            raise ValueError(f"digest_day must be one of {sorted(days)}, got '{v}'")
        return v.lower()

    @field_validator("digest_hour")
    @classmethod
    def validate_digest_hour(cls, v: int) -> int:
        if not 0 <= v <= 23:
            raise ValueError(f"digest_hour must be 0–23, got {v}")
        return v

    @model_validator(mode="after")
    def require_auth_pair(self) -> "Settings":
        if bool(self.web_ui_username) != bool(self.web_ui_password):
            raise ValueError("WEB_UI_USERNAME and WEB_UI_PASSWORD must be set together (or both left unset).")
        return self

    @model_validator(mode="after")
    def require_alert_target(self) -> "Settings":
        has_email = bool(self.alert_email_to and self.alert_email_smtp_host)
        has_discord = bool(self.alert_discord_webhook)
        if not has_email and not has_discord:
            raise ValueError(
                "No alert target configured. "
                "Set ALERT_DISCORD_WEBHOOK or both ALERT_EMAIL_TO and ALERT_EMAIL_SMTP_HOST."
            )
        return self

    @property
    def db_path(self) -> str:
        return f"{self.data_path}/pvewatch.db"
