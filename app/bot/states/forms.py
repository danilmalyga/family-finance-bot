from aiogram.fsm.state import State, StatesGroup


class AddExpense(StatesGroup):
    waiting_text = State()


class AddIncome(StatesGroup):
    waiting_text = State()


class PurchaseCheck(StatesGroup):
    waiting_text = State()
    waiting_followup = State()


class SettingsFlow(StatesGroup):
    waiting_budget = State()
    waiting_payment = State()
    waiting_groceries_budget = State()


class MandatoryPaymentFlow(StatesGroup):
    waiting_amount = State()
