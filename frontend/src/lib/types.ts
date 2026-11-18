/** Types mirroring the backend API schemas (backend/app/modules/<module>/schemas.py). */

export type Role = "owner" | "admin" | "staff";
export type Language = "hi" | "hinglish" | "en" | "pa";

export interface PublicUser {
  id: string;
  phone: string;
  name: string;
  preferred_language: Language;
  must_change_password: boolean;
  created_at: string;
}

export interface Membership {
  shop_id: string;
  shop_name: string;
  role: Role;
}

export interface Me {
  user: PublicUser;
  active_shop_id: string | null;
  memberships: Membership[];
}

export interface Shop {
  id: string;
  name: string;
  business_type: string;
  address: string | null;
  city: string | null;
  state: string | null;
  pincode: string | null;
  timezone: string;
  default_language: Language;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface CurrentShop {
  shop: Shop;
  role: Role;
}

export interface MyShop {
  shop_id: string;
  name: string;
  role: Role;
  is_active: boolean;
}

export interface Member {
  id: string;
  user_id: string;
  name: string;
  phone_masked: string;
  role: Role;
  status: "active" | "removed";
  credit_limit_paise: number | null;
  joined_at: string;
  removed_at: string | null;
}

export interface MemberPage {
  items: Member[];
  total: number;
  limit: number;
  offset: number;
}

export interface MemberAdded {
  member: Member;
  account_created: boolean;
}

export interface SessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  user_agent: string | null;
  current: boolean;
}

export interface ErrorDetail {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}
