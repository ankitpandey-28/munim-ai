"""Verified shop context for a request (built by app.api.deps.get_shop_context)."""

import uuid
from dataclasses import dataclass

from app.modules.identity.models import AuthSession, User
from app.modules.shops.models import Shop, ShopMember


@dataclass
class ShopContext:
    user: User
    session: AuthSession
    membership: ShopMember
    shop: Shop

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def shop_id(self) -> uuid.UUID:
        return self.shop.id

    @property
    def role(self) -> str:
        return self.membership.role
