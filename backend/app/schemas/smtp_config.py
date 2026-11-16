from typing import Optional
from pydantic import BaseModel, Field


class SmtpConfigResponse(BaseModel):
    enabled: bool = True
    host: str = "localhost"
    port: int = 587
    username: Optional[str] = None
    from_email: str = "noreply@nibiaa.com"
    from_name: str = "IoT Platform"
    use_tls: bool = True
    use_ssl: bool = False
    has_password: bool = False
    configured: bool = False


class SmtpConfigUpdate(BaseModel):
    enabled: bool = True
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535, default=587)
    username: Optional[str] = None
    password: Optional[str] = None
    from_email: str = Field(min_length=3)
    from_name: str = Field(default="IoT Platform")
    use_tls: bool = True
    use_ssl: bool = False
