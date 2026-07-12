from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class TransactionType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    SAVING = "saving"
    DEBT_PAYMENT = "debt_payment"


class TransactionSource(StrEnum):
    TEXT = "text"
    RECEIPT = "receipt"
    MANUAL = "manual"
    VOICE = "voice"


class TransactionStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class PurchaseDecision(StrEnum):
    APPROVE = "approve"
    CAUTION = "caution"
    POSTPONE = "postpone"


class WishlistStatus(StrEnum):
    CONSIDERING = "considering"
    POSTPONED = "postponed"
    APPROVED = "approved"
    PURCHASED = "purchased"
    CANCELLED = "cancelled"
