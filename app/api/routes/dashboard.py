from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import escape
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_family_id, session_dep
from app.config import Settings, get_settings
from app.db.models.transaction import TransactionItem
from app.domain.enums import TransactionType
from app.repositories.family import FamilyRepository
from app.repositories.transactions import TransactionRepository
from app.services.budget_engine import BudgetEngine
from app.utils.money import money

router = APIRouter(tags=["dashboard"])


@dataclass(frozen=True)
class CategoryExpenseDetail:
    id: UUID
    target: str
    name: str
    amount: Decimal
    transaction_date: date
    category_code: str


@dataclass(frozen=True)
class DashboardCategoryOption:
    code: str
    name: str


class CategoryChangePayload(BaseModel):
    category_code: str


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    key: str | None = Query(default=None),
    test: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> HTMLResponse:
    validate_dashboard_key(key, settings)

    snapshot = await BudgetEngine(session).get_snapshot(family_id, date.today())
    transactions = await TransactionRepository(session).confirmed_between(
        family_id,
        snapshot.period_start,
        snapshot.period_end,
    )
    categories = await FamilyRepository(session).list_categories(family_id)
    category_details = build_category_expense_details(transactions, categories)
    category_options = [
        DashboardCategoryOption(code=category.code, name=category.name) for category in categories
    ]
    html = render_dashboard(
        snapshot=snapshot,
        category_details=category_details,
        category_options=category_options,
        show_test_panel=test,
    )
    return HTMLResponse(html)


@router.patch("/dashboard/api/transaction-items/{item_id}/category")
async def update_dashboard_item_category(
    item_id: UUID,
    payload: CategoryChangePayload,
    key: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> dict[str, bool]:
    validate_dashboard_key(key, settings)
    item = await session.get(TransactionItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    tx = await TransactionRepository(session).get(item.transaction_id)
    if tx is None or tx.family_id != family_id:
        raise HTTPException(status_code=404, detail="Transaction not found")
    category = await FamilyRepository(session).get_category_by_code(family_id, payload.category_code)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    item.category_id = category.id
    await session.commit()
    return {"updated": True}


@router.patch("/dashboard/api/transactions/{transaction_id}/category")
async def update_dashboard_transaction_category(
    transaction_id: UUID,
    payload: CategoryChangePayload,
    key: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> dict[str, bool]:
    validate_dashboard_key(key, settings)
    tx = await TransactionRepository(session).get(transaction_id)
    if tx is None or tx.family_id != family_id:
        raise HTTPException(status_code=404, detail="Transaction not found")
    category = await FamilyRepository(session).get_category_by_code(family_id, payload.category_code)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    tx.category_id = category.id
    await session.commit()
    return {"updated": True}


def validate_dashboard_key(key: str | None, settings: Settings) -> None:
    expected = settings.api_secret_key.get_secret_value() if settings.api_secret_key else ""
    if expected and key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dashboard key")


def render_dashboard(
    snapshot: object,
    category_details: dict[str, list[CategoryExpenseDetail]] | None = None,
    category_options: list[DashboardCategoryOption] | None = None,
    show_test_panel: bool = False,
) -> str:
    today = date.today()
    income = snapshot.total_income  # type: ignore[attr-defined]
    mandatory = snapshot.mandatory_remaining  # type: ignore[attr-defined]
    discretionary = snapshot.discretionary_spent  # type: ignore[attr-defined]
    savings = snapshot.total_savings  # type: ignore[attr-defined]
    available = snapshot.available_to_spend  # type: ignore[attr-defined]
    factual_available = money(income - mandatory - snapshot.total_expenses)  # type: ignore[attr-defined]
    future_mandatory = future_payments_total(snapshot.upcoming_payments, today)  # type: ignore[attr-defined]
    paid_mandatory = max(Decimal("0"), mandatory - future_mandatory)
    category_cards = render_category_cards(
        snapshot.category_summaries,  # type: ignore[attr-defined]
        category_details or {},
        category_options or [],
    )
    mandatory_overview = render_mandatory_overview(snapshot.upcoming_payments, today)  # type: ignore[attr-defined]
    mandatory_progress = render_mandatory_payment_progress(
        snapshot.mandatory_payment_progress  # type: ignore[attr-defined]
    )
    groceries_focus = render_groceries_focus(snapshot)
    groceries_week_history = render_groceries_week_history(snapshot)
    available_status = "Бюджет превышен" if available < 0 else "Бюджет в норме"
    test_panel = (
        render_test_panel(
            income=income,
            mandatory=mandatory,
            paid_mandatory=paid_mandatory,
            groceries_weekly_limit=getattr(
                getattr(snapshot, "groceries_week", None),
                "weekly_limit",
                Decimal("0"),
            ),
            groceries_spent=snapshot.groceries_cycle_spent,  # type: ignore[attr-defined]
            groceries_current_week_remaining=getattr(
                getattr(snapshot, "groceries_week", None),
                "remaining",
                Decimal("0"),
            ),
            remaining_weeks=Decimal(snapshot.groceries_cycle_remaining_weeks),  # type: ignore[attr-defined]
            discretionary=discretionary,
            savings=savings,
            savings_target=snapshot.savings_target,  # type: ignore[attr-defined]
            reserve_gap=snapshot.reserve_gap,  # type: ignore[attr-defined]
            days_until_next_income=Decimal(snapshot.days_until_next_income),  # type: ignore[attr-defined]
        )
        if show_test_panel
        else ""
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Финансовый обзор</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #20242a;
      --muted: #69717d;
      --line: #d9dee6;
      --accent: #176b5d;
      --warn: #b7791f;
      --bad: #b42318;
      --blue: #2457a6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 22px 28px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{ margin: 0; font-size: 24px; font-weight: 700; }}
    .period {{ margin-top: 4px; color: var(--muted); }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 22px;
      display: grid;
      gap: 18px;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 14px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ margin-top: 6px; font-size: 25px; font-weight: 750; }}
    .good {{ color: var(--accent); }}
    .warn {{ color: var(--warn); }}
    .bad {{ color: var(--bad); }}
    .grid {{
      display: grid;
      grid-template-columns: 1.25fr .75fr;
      gap: 18px;
    }}
    .overview-grid {{
      display: grid;
      grid-template-columns: minmax(280px, .9fr) minmax(0, 1.1fr);
      gap: 18px;
      align-items: stretch;
    }}
    .overview-side {{
      display: grid;
      gap: 18px;
    }}
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
    h3 {{
      margin: 14px 0 8px;
      font-size: 14px;
      color: var(--muted);
      font-weight: 700;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 22px;
      display: grid;
      gap: 14px;
    }}
    .hero-label {{ color: var(--muted); font-size: 14px; }}
    .hero-value {{ font-size: 44px; line-height: 1; font-weight: 800; color: var(--accent); }}
    .hero-value.danger {{ color: var(--bad); }}
    .hero-note {{ color: var(--muted); max-width: 720px; }}
    .status {{
      display: inline-flex;
      width: fit-content;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      font-weight: 700;
      background: #e8f3ef;
      color: var(--accent);
    }}
    .status.warning {{ background: #fff4df; color: var(--warn); }}
    .status.danger {{ background: #ffe9e6; color: var(--bad); }}
    .grocery-card.warning {{ border-color: #e2b55f; }}
    .grocery-card.danger {{ border-color: #db8b82; }}
    .week-history-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .week-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      display: grid;
      grid-template-columns: 78px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      background: #fff;
    }}
    .week-card.green {{ border-color: #9dc8b9; }}
    .week-card.yellow {{ border-color: #e4bd68; }}
    .week-card.red {{ border-color: #e09b92; }}
    .week-donut {{
      width: 78px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: conic-gradient(var(--week-color) var(--pct), #e6eaf0 0);
      display: grid;
      place-items: center;
    }}
    .week-donut::after {{
      content: "";
      width: 46px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: #fff;
    }}
    .week-card.green {{ --week-color: #2e8f6f; }}
    .week-card.yellow {{ --week-color: #b98513; }}
    .week-card.red {{ --week-color: #c84f43; }}
    .week-meta {{ display: grid; gap: 5px; min-width: 0; }}
    .week-title {{ font-weight: 750; }}
    .week-line {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      font-size: 13px;
      color: var(--muted);
    }}
    .week-line strong {{ color: var(--ink); }}
    .mandatory-progress-list {{
      display: grid;
      gap: 14px;
    }}
    .mandatory-progress-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: center;
      padding: 12px 0;
      border-top: 1px solid var(--line);
    }}
    .mandatory-progress-item:first-child {{ border-top: 0; padding-top: 0; }}
    .progress-main {{
      display: grid;
      gap: 7px;
      min-width: 0;
    }}
    .progress-title {{
      font-weight: 750;
      overflow-wrap: anywhere;
    }}
    .progress-subtitle {{
      color: var(--muted);
      font-size: 13px;
    }}
    .progress-bar {{
      height: 9px;
      border-radius: 999px;
      background: #e6eaf0;
      overflow: hidden;
    }}
    .progress-fill {{
      height: 100%;
      width: var(--pct);
      border-radius: 999px;
      background: var(--accent);
    }}
    .progress-fill.warn {{ background: var(--warn); }}
    .progress-fill.bad {{ background: var(--bad); }}
    .progress-amount {{
      font-weight: 800;
      white-space: nowrap;
      text-align: right;
    }}
    .grocery-ring-wrap {{
      display: grid;
      place-items: center;
      padding: 8px 0 14px;
    }}
    .grocery-ring {{
      width: 210px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: conic-gradient(var(--accent) var(--pct), #e6eaf0 0);
      display: grid;
      place-items: center;
    }}
    .grocery-card.warning .grocery-ring {{ background: conic-gradient(var(--warn) var(--pct), #e6eaf0 0); }}
    .grocery-card.danger .grocery-ring {{ background: conic-gradient(var(--bad) var(--pct), #e6eaf0 0); }}
    .grocery-ring-inner {{
      width: 132px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: var(--panel);
      display: grid;
      place-items: center;
      text-align: center;
      padding: 12px;
    }}
    .ring-label {{ color: var(--muted); font-size: 13px; }}
    .ring-value {{ font-size: 24px; font-weight: 800; }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 12px;
    }}
    .section-title .hint {{ color: var(--muted); font-size: 13px; }}
    .breakdown {{
      display: grid;
      gap: 2px;
    }}
    .breakdown-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      padding: 8px 0;
      border-top: 1px solid var(--line);
    }}
    .breakdown-row:first-child {{ border-top: 0; }}
    .breakdown-row.total {{
      margin-top: 6px;
      border-top: 2px solid var(--ink);
      font-weight: 800;
    }}
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .mini-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px;
      background: #fbfcfd;
      display: grid;
      gap: 8px;
    }}
    details.mini-card {{
      display: block;
    }}
    .mini-summary {{
      list-style: none;
      cursor: pointer;
      display: grid;
      gap: 8px;
    }}
    .mini-summary::-webkit-details-marker {{ display: none; }}
    .mini-summary::after {{
      content: "Показать покупки";
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }}
    details[open] .mini-summary::after {{ content: "Скрыть покупки"; }}
    .mini-title {{ font-weight: 700; overflow-wrap: anywhere; }}
    .mini-line {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .bar {{
      height: 12px;
      background: #edf0f4;
      border-radius: 99px;
      overflow: hidden;
      border: 1px solid var(--line);
    }}
    .fill {{ height: 100%; background: var(--accent); width: 0; }}
    .fill.warn {{ background: var(--warn); }}
    .fill.blue {{ background: var(--blue); }}
    .metric {{ display: grid; gap: 8px; margin-bottom: 14px; }}
    .row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      padding: 9px 0;
      border-top: 1px solid var(--line);
    }}
    .row:first-child {{ border-top: 0; }}
    .name {{ min-width: 0; overflow-wrap: anywhere; }}
    .amount {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .muted {{ color: var(--muted); }}
    .two {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }}
    .donuts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .donut-card {{
      display: grid;
      grid-template-columns: 150px minmax(0, 1fr);
      gap: 18px;
      align-items: center;
    }}
    .donut {{
      width: 150px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: conic-gradient(var(--accent) var(--pct), #e6eaf0 0);
      display: grid;
      place-items: center;
    }}
    .donut::after {{
      content: "";
      width: 92px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: var(--panel);
    }}
    .legend {{ display: grid; gap: 8px; }}
    .legend-row {{
      display: grid;
      grid-template-columns: 12px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
    }}
    .swatch {{ width: 12px; height: 12px; border-radius: 3px; background: var(--accent); }}
    .swatch.rest {{ background: #e6eaf0; border: 1px solid var(--line); }}
    .payments-list {{
      display: grid;
      gap: 10px;
    }}
    .payment-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      padding: 11px 0;
      border-top: 1px solid var(--line);
      align-items: start;
    }}
    .payment-item:first-child {{ border-top: 0; padding-top: 0; }}
    .payment-title {{
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .payment-date {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 13px;
    }}
    .payment-line {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      padding: 10px 0;
      border-top: 1px solid var(--line);
      align-items: baseline;
    }}
    .payment-line:first-child {{ border-top: 0; padding-top: 0; }}
    .payment-amount {{
      font-variant-numeric: tabular-nums;
      font-weight: 700;
      white-space: nowrap;
      text-align: right;
    }}
    .detail-list {{
      display: grid;
      gap: 8px;
      margin-top: 12px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
    }}
    .detail-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
      font-size: 13px;
    }}
    .detail-name {{ overflow-wrap: anywhere; }}
    .detail-date {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }}
    .detail-amount {{
      font-variant-numeric: tabular-nums;
      font-weight: 700;
      white-space: nowrap;
    }}
    .category-select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 8px;
      margin-top: 7px;
      background: var(--panel);
      color: var(--ink);
      font: inherit;
      font-size: 13px;
    }}
    .detail-error {{
      color: var(--bad);
      font-size: 12px;
      margin-top: 4px;
    }}
    .test-panel {{
      border-color: #b8c7d9;
      background: #f9fbfd;
    }}
    .test-switch {{
      display: inline-flex;
      align-items: center;
      gap: 9px;
      font-weight: 700;
      cursor: pointer;
    }}
    .test-switch input {{
      width: 18px;
      height: 18px;
    }}
    .test-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .field {{
      display: grid;
      gap: 5px;
    }}
    .field label {{
      color: var(--muted);
      font-size: 12px;
    }}
    .field input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      background: var(--panel);
    }}
    .test-note {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 900px) {{
      .kpis, .grid, .overview-grid, .two, .donuts, .cards-grid, .test-grid {{ grid-template-columns: 1fr; }}
      .hero-value {{ font-size: 36px; }}
      .donut-card {{ grid-template-columns: 120px minmax(0, 1fr); }}
      .donut {{ width: 120px; }}
      .donut::after {{ width: 74px; }}
      main {{ padding: 14px; }}
      header {{ padding: 18px 16px 10px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Семейные финансы</h1>
    <div class="period">{format_date(snapshot.period_start)} — {format_date(snapshot.period_end)} · До следующей зарплаты: {snapshot.days_until_next_income} дн.</div>
  </header>
  <main>
    <section class="overview-grid">
      {groceries_focus}
      <div class="overview-side">
        <div class="hero">
          <span class="status {'danger' if available < 0 else ''}">{available_status}</span>
          <div class="hero-label">Доступно к тратам</div>
          <div class="hero-value {'danger' if available < 0 else ''}" data-test="available-main">{format_money(available)}</div>
          <div class="hero-note">Свободные деньги после обязательных платежей, продуктового резерва и уже совершённых расходов.</div>
        </div>
        <div class="card">
          <h2>Безопасный лимит</h2>
          <div class="value {'bad' if snapshot.safe_daily_limit < 0 else 'blue'}" data-test="daily-limit">{format_money(snapshot.safe_daily_limit)} / день</div>
          <div class="muted" data-test="daily-note">До зарплаты: {snapshot.days_until_next_income} дн.</div>
          <div class="hero-note">Максимальная средняя сумма свободных расходов в день, чтобы не выйти за бюджет до следующего дохода.</div>
        </div>
        <div class="card">
          <h2>Обязательные платежи</h2>
          {mandatory_overview}
        </div>
      </div>
    </section>

    {test_panel}

    {mandatory_progress}

    <section class="card">
      <h2>Расходы по категориям</h2>
      {category_cards}
    </section>

    {groceries_week_history}

    <section class="card">
      <h2>Фактический остаток</h2>
      <div class="hero-value {'danger' if factual_available < 0 else ''}">{format_money(factual_available)}</div>
      <div class="hero-note">Зарплата минус все обязательные платежи зарплатного цикла и фактические траты.</div>
      <div class="breakdown">
        <div class="breakdown-row"><span>Зарплата</span><strong>{format_money(income)}</strong></div>
        <div class="breakdown-row"><span>Обязательные платежи цикла</span><strong>−{format_money(mandatory)}</strong></div>
        <div class="breakdown-row"><span>Фактические траты</span><strong>−{format_money(snapshot.total_expenses)}</strong></div>
        <div class="breakdown-row total"><span>Фактический остаток</span><strong>{format_money(factual_available)}</strong></div>
      </div>
    </section>
  </main>
  <script>
    (() => {{
      const params = new URLSearchParams(window.location.search);
      const key = params.get("key") || "";
      document.querySelectorAll("[data-category-editor]").forEach((select) => {{
        select.addEventListener("change", async () => {{
          const target = select.dataset.target;
          const id = select.dataset.id;
          const categoryCode = select.value;
          const row = select.closest(".detail-row");
          const error = row?.querySelector(".detail-error");
          if (error) error.textContent = "";
          if (!target || !id || !categoryCode) return;
          const endpoint = target === "item"
            ? `/dashboard/api/transaction-items/${{id}}/category?key=${{encodeURIComponent(key)}}`
            : `/dashboard/api/transactions/${{id}}/category?key=${{encodeURIComponent(key)}}`;
          select.disabled = true;
          try {{
            const response = await fetch(endpoint, {{
              method: "PATCH",
              headers: {{"Content-Type": "application/json"}},
              body: JSON.stringify({{category_code: categoryCode}}),
            }});
            if (!response.ok) {{
              throw new Error("Не удалось сохранить категорию");
            }}
            window.location.reload();
          }} catch (err) {{
            if (error) error.textContent = "Не удалось сохранить категорию.";
            select.disabled = false;
          }}
        }});
      }});
    }})();
  </script>
</body>
</html>"""


def kpi(label: str, value: Decimal, tone: str = "", key: str = "") -> str:
    attr = f' data-test="{escape(key)}"' if key else ""
    return f"""
      <div class="card">
        <div class="label">{escape(label)}</div>
        <div class="value {tone}"{attr}>{format_money(value)}</div>
      </div>
    """


def metric(label: str, value: Decimal, pct: int, tone: str, suffix: str = "") -> str:
    right = f"{format_money(value)} {escape(suffix)}".strip()
    return f"""
      <div class="metric">
        <div class="row"><div class="name">{escape(label)}</div><div class="amount">{right}</div></div>
        <div class="bar"><div class="fill {tone}" style="width:{pct}%"></div></div>
      </div>
    """


def render_breakdown(
    income: Decimal,
    mandatory: Decimal,
    groceries_reserved: Decimal,
    discretionary: Decimal,
    savings: Decimal,
    savings_remaining: Decimal,
    reserve_gap: Decimal,
    available: Decimal,
) -> str:
    rows = [
        ("Доходы", income, "", "breakdown-income"),
        ("Обязательные платежи", mandatory, "−", "breakdown-mandatory"),
        ("Продукты до конца цикла", groceries_reserved, "−", "breakdown-groceries"),
        ("Другие расходы", discretionary, "−", "breakdown-discretionary"),
        ("Накопления", savings, "−", "breakdown-savings"),
        ("Остаток цели накоплений", savings_remaining, "−", "breakdown-savings-remaining"),
        ("Недобор резерва", reserve_gap, "−", "breakdown-reserve-gap"),
    ]
    body = "".join(
        f'<div class="breakdown-row"><span>{escape(label)}</span><strong data-test="{key}">{sign}{format_money(value)}</strong></div>'
        for label, value, sign, key in rows
    )
    return (
        f'<div class="breakdown">{body}'
        f'<div class="breakdown-row total"><span>Доступно к тратам</span><strong data-test="breakdown-available">{format_money(available)}</strong></div>'
        "</div>"
    )


def render_test_panel(
    income: Decimal,
    mandatory: Decimal,
    paid_mandatory: Decimal,
    groceries_weekly_limit: Decimal,
    groceries_spent: Decimal,
    groceries_current_week_remaining: Decimal,
    remaining_weeks: Decimal,
    discretionary: Decimal,
    savings: Decimal,
    savings_target: Decimal,
    reserve_gap: Decimal,
    days_until_next_income: Decimal,
) -> str:
    return f"""
    <section class="card test-panel">
      <label class="test-switch">
        <input type="checkbox" id="testMode">
        Тестовая модель
      </label>
      <div class="test-note">
        При включении страница считает цифры из полей ниже. База данных и Telegram-настройки не меняются.
      </div>
      <div class="test-grid">
        {test_input("testIncome", "Зарплата", income)}
        {test_input("testMandatory", "Обязательные платежи всего", mandatory)}
        {test_input("testMandatoryPaid", "Уже оплачено обязательных", paid_mandatory)}
        {test_input("testGroceriesWeekly", "Бюджет продуктов на неделю", groceries_weekly_limit)}
        {test_input("testGroceriesSpent", "Продукты уже потрачено", groceries_spent)}
        {test_input("testGroceriesCurrentRemaining", "Остаток продуктов текущей недели", groceries_current_week_remaining)}
        {test_input("testRemainingWeeks", "Будущие полные продуктовые недели", remaining_weeks)}
        {test_input("testOther", "Обычные расходы", discretionary)}
        {test_input("testSavings", "Накопления уже внесены", savings)}
        {test_input("testSavingsTarget", "Цель накоплений", savings_target)}
        {test_input("testReserveGap", "Недобор резерва", reserve_gap)}
        {test_input("testDays", "Дней до зарплаты", days_until_next_income)}
      </div>
    </section>
    <script>
      (() => {{
        const moneyKeys = [
          "available-main", "cycle-balance", "balance", "total-expenses", "discretionary",
          "daily-limit", "breakdown-income", "breakdown-mandatory", "breakdown-groceries",
          "breakdown-discretionary", "breakdown-savings", "breakdown-savings-remaining",
          "breakdown-reserve-gap", "breakdown-available", "forecast-balance",
          "forecast-future-groceries", "forecast-future-mandatory", "forecast-available",
          "free-initial", "free-spent", "free-available", "groceries-spent",
          "groceries-weekly", "groceries-remaining", "groceries-cycle-spent",
          "groceries-future-plan", "groceries-cycle-forecast", "actual-income",
          "actual-expenses", "actual-savings", "actual-balance"
        ];
        const original = new Map();
        for (const key of moneyKeys) {{
          original.set(key, [...document.querySelectorAll(`[data-test="${{key}}"]`)].map((node) => node.textContent));
        }}
        original.set("daily-note", [...document.querySelectorAll('[data-test="daily-note"]')].map((node) => node.textContent));

        const field = (id) => {{
          const raw = document.getElementById(id)?.value || "0";
          const value = Number(String(raw).replace(",", "."));
          return Number.isFinite(value) ? value : 0;
        }};
        const euro = (value, signed = false) => {{
          const prefix = signed && value > 0 ? "−" : "";
          return prefix + new Intl.NumberFormat("ru-RU", {{
            style: "currency",
            currency: "EUR",
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          }}).format(Math.abs(value)).replace(/\\s€/, " €");
        }};
        const setText = (key, text) => {{
          document.querySelectorAll(`[data-test="${{key}}"]`).forEach((node) => {{
            node.textContent = text;
          }});
        }};
        const setMoney = (key, value, signed = false) => setText(key, euro(value, signed));
        const setDailyLimit = (value) => setText("daily-limit", `${{euro(value)}} / день`);
        const setDonut = (key, used, remaining) => {{
          const total = Math.max(0, used) + Math.max(0, remaining);
          const pct = total > 0 ? Math.round((Math.max(0, used) / total) * 100) : 0;
          document.querySelectorAll(`[data-donut="${{key}}"]`).forEach((node) => {{
            node.style.setProperty("--pct", `${{pct}}%`);
          }});
          setMoney(`${{key}}-used`, used);
          setMoney(`${{key}}-remaining`, remaining);
        }};
        const restore = () => {{
          for (const [key, values] of original.entries()) {{
            document.querySelectorAll(`[data-test="${{key}}"]`).forEach((node, index) => {{
              node.textContent = values[index] || "";
            }});
          }}
        }};
        const recalc = () => {{
          if (!document.getElementById("testMode")?.checked) {{
            restore();
            return;
          }}
          const income = field("testIncome");
          const mandatory = field("testMandatory");
          const paidMandatory = field("testMandatoryPaid");
          const groceriesWeekly = field("testGroceriesWeekly");
          const groceriesSpent = field("testGroceriesSpent");
          const groceriesCurrentRemaining = Math.max(0, field("testGroceriesCurrentRemaining"));
          const remainingWeeks = Math.max(0, field("testRemainingWeeks"));
          const other = field("testOther");
          const savings = field("testSavings");
          const savingsTarget = field("testSavingsTarget");
          const reserveGap = field("testReserveGap");
          const days = Math.max(1, Math.round(field("testDays")));

          const groceriesReserve = groceriesSpent + groceriesCurrentRemaining + groceriesWeekly * remainingWeeks;
          const futureGroceries = Math.max(0, groceriesReserve - groceriesSpent);
          const futureMandatory = Math.max(0, mandatory - paidMandatory);
          const savingsRemaining = Math.max(0, savingsTarget - savings);
          const available = income - mandatory - groceriesReserve - other - savings - savingsRemaining - reserveGap;
          const freeInitial = income - mandatory - groceriesReserve - savingsTarget;
          const actualExpenses = paidMandatory + groceriesSpent + other;
          const balance = income - actualExpenses - savings;
          const cycleBalance = income - mandatory - groceriesReserve;
          const daily = available / days;
          const groceriesWeekRemaining = groceriesCurrentRemaining;
          const periodUsed = mandatory + groceriesReserve + other + savings;

          setMoney("available-main", available);
          setMoney("cycle-balance", cycleBalance);
          setMoney("balance", balance);
          setMoney("total-expenses", actualExpenses);
          setMoney("discretionary", other);
          setDailyLimit(daily);
          setMoney("breakdown-income", income);
          setMoney("breakdown-mandatory", mandatory, true);
          setMoney("breakdown-groceries", groceriesReserve, true);
          setMoney("breakdown-discretionary", other, true);
          setMoney("breakdown-savings", savings, true);
          setMoney("breakdown-savings-remaining", savingsRemaining, true);
          setMoney("breakdown-reserve-gap", reserveGap, true);
          setMoney("breakdown-available", available);
          setMoney("forecast-balance", balance);
          setMoney("forecast-future-groceries", futureGroceries);
          setMoney("forecast-future-mandatory", futureMandatory);
          setMoney("forecast-available", available);
          setMoney("free-initial", freeInitial);
          setMoney("free-spent", other);
          setMoney("free-available", available);
          setText("daily-note", `До зарплаты: ${{days}} дн.`);
          setMoney("groceries-spent", groceriesSpent);
          setMoney("groceries-weekly", groceriesWeekly);
          setMoney("groceries-remaining", groceriesWeekRemaining);
          setMoney("grocery-center-remaining", groceriesWeekRemaining);
          setMoney("groceries-cycle-spent", groceriesSpent);
          setMoney("groceries-future-plan", futureGroceries);
          setMoney("groceries-cycle-forecast", groceriesReserve);
          setText("grocery-used-pct", `${{Math.min(100, Math.max(0, Math.round((groceriesSpent / Math.max(0.01, groceriesWeekly)) * 100)))}}%`);
          setMoney("actual-income", income);
          setMoney("actual-expenses", actualExpenses, true);
          setMoney("actual-savings", savings, true);
          setMoney("actual-balance", balance);
          setDonut("expense", other, Math.max(0, available));
          setDonut("period", periodUsed, Math.max(0, available));
          setDonut("grocery", groceriesSpent, groceriesWeekRemaining);
        }};

        document.getElementById("testMode")?.addEventListener("change", recalc);
        document.querySelectorAll(".test-panel input").forEach((input) => {{
          input.addEventListener("input", recalc);
          input.addEventListener("change", recalc);
        }});
      }})();
    </script>
    """


def test_input(field_id: str, label: str, value: Decimal) -> str:
    return f"""
      <div class="field">
        <label for="{escape(field_id)}">{escape(label)}</label>
        <input id="{escape(field_id)}" type="number" step="0.01" value="{decimal_for_input(value)}">
      </div>
    """


def render_groceries_focus(snapshot: object) -> str:
    groceries_week = snapshot.groceries_week  # type: ignore[attr-defined]
    if groceries_week is None:
        return """
          <section class="card grocery-card">
            <h2>Продукты на неделю</h2>
            <div class="muted">Недельный бюджет продуктов не настроен.</div>
          </section>
        """
    weekly_limit = groceries_week.weekly_limit  # type: ignore[attr-defined]
    base_weekly_limit = groceries_week.base_weekly_limit  # type: ignore[attr-defined]
    carryover = groceries_week.carryover  # type: ignore[attr-defined]
    spent = groceries_week.spent  # type: ignore[attr-defined]
    remaining = groceries_week.remaining  # type: ignore[attr-defined]
    overspent = max(Decimal("0"), money(spent - weekly_limit))
    pct = percent(spent, weekly_limit)
    if overspent > 0:
        tone = "danger"
        status = "Продуктовый бюджет превышен"
    elif pct >= 80:
        tone = "warning"
        status = "Близко к недельному лимиту"
    else:
        tone = ""
        status = "Бюджет в норме"
    overspent_row = (
        f'<div class="row"><div class="name muted">Перерасход</div><div class="amount bad">{format_money(overspent)}</div></div>'
        if overspent > 0
        else ""
    )
    carryover_class = "bad" if carryover < 0 else "good"
    carryover_row = (
        f'<div class="row"><div class="name muted">Перенос прошлых недель</div><div class="amount {carryover_class}">{format_money(carryover)}</div></div>'
        if carryover != 0
        else ""
    )
    return f"""
      <section class="card grocery-card {tone}">
        <div class="section-title"><h2>Продукты на неделю</h2><span class="status {tone}">{status}</span></div>
        <div class="grocery-ring-wrap">
          <div class="grocery-ring" style="--pct:{pct}%" data-donut="grocery">
            <div class="grocery-ring-inner">
              <div>
                <div class="ring-label">Осталось</div>
                <div class="ring-value" data-test="grocery-center-remaining">{format_money(remaining)}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="row"><div class="name muted">Потрачено</div><div class="amount"><span data-test="groceries-spent">{format_money(spent)}</span> из <span data-test="groceries-weekly">{format_money(weekly_limit)}</span></div></div>
        <div class="row"><div class="name muted">Базовый недельный бюджет</div><div class="amount">{format_money(base_weekly_limit)}</div></div>
        {carryover_row}
        <div class="row"><div class="name muted">Использовано</div><div class="amount" data-test="grocery-used-pct">{pct}%</div></div>
        <div class="row"><div class="name muted">Неделя</div><div class="amount">{format_date_short(groceries_week.week_start)} — {format_date_short(groceries_week.week_end)}</div></div>
        {overspent_row}
      </section>
    """


def render_groceries_week_history(snapshot: object) -> str:
    history = getattr(snapshot, "groceries_week_history", [])
    completed_weeks = [
        week
        for week in history
        if getattr(week, "week_end", date.min) < date.today()
    ]
    if not completed_weeks:
        return ""
    cards = []
    for index, week in enumerate(completed_weeks, start=1):
        adjusted_limit = week.adjusted_weekly_limit
        spent = week.spent
        pct = percent(spent, adjusted_limit)
        status = week.status
        balance = week.balance
        balance_label = "Остаток" if balance >= 0 else "Перерасход"
        balance_class = "good" if balance >= 0 else "bad"
        status_label = {
            "green": "В бюджете",
            "yellow": "Перерасход до 5%",
            "red": "Перерасход больше 5%",
        }.get(status, "В бюджете")
        cards.append(
            f"""
            <div class="week-card {escape(status)}">
              <div class="week-donut" style="--pct:{pct}%"></div>
              <div class="week-meta">
                <div class="week-title">Неделя {index}: {format_date_short(week.week_start)} — {format_date_short(week.week_end)}</div>
                <div class="week-line"><span>Статус</span><strong>{status_label}</strong></div>
                <div class="week-line"><span>Потрачено</span><strong>{format_money(spent)} из {format_money(adjusted_limit)}</strong></div>
                <div class="week-line"><span>{balance_label}</span><strong class="{balance_class}">{format_money(abs(balance))}</strong></div>
              </div>
            </div>
            """
        )
    return f"""
      <section class="card">
        <div class="section-title">
          <h2>Продуктовые недели</h2>
          <span class="hint">Перенос остатка или перерасхода влияет на следующую неделю</span>
        </div>
        <div class="week-history-grid">{"".join(cards)}</div>
      </section>
    """


def render_mandatory_overview(payments: list[object], today: date) -> str:
    if not payments:
        return '<div class="muted">Обязательные платежи не настроены.</div>'
    rows = []
    for payment in payments:
        rows.append(
            f"""
            <div class="payment-line">
              <div class="payment-title">{escape(clean_payment_name(payment.name))}</div>
              <div class="payment-amount">{format_money(payment.amount)}</div>
            </div>
            """  # type: ignore[attr-defined]
        )
    return f'<div class="payments-list">{"".join(rows)}</div>'


def render_mandatory_payment_progress(items: list[object]) -> str:
    if not items:
        return """
          <section class="card">
            <h2>Обязательные платежи</h2>
            <div class="muted">Обязательные платежи не настроены.</div>
          </section>
        """
    rows = []
    for item in items:
        amount = money(item.amount)  # type: ignore[attr-defined]
        spent = money(item.spent)  # type: ignore[attr-defined]
        pct = min(100, percent(spent, amount))
        fill_tone = "bad" if spent > amount else "warn" if pct >= 80 else ""
        category_text = (
            f'<div class="progress-subtitle">Категория: {escape(item.category_name)}</div>'
            if getattr(item, "category_name", None)
            else ""
        )
        rows.append(
            f"""
            <div class="mandatory-progress-item">
              <div class="progress-main">
                <div class="progress-title">{escape(clean_payment_name(item.name))}</div>
                {category_text}
                <div class="progress-bar"><div class="progress-fill {fill_tone}" style="--pct:{pct}%"></div></div>
              </div>
              <div class="progress-amount">{format_money(spent)} из {format_money(amount)}</div>
            </div>
            """  # type: ignore[attr-defined]
        )
    return f"""
      <section class="card">
        <div class="section-title">
          <h2>Обязательные платежи</h2>
          <span class="hint">Фактические траты по категориям за зарплатный цикл</span>
        </div>
        <div class="mandatory-progress-list">{"".join(rows)}</div>
      </section>
    """


def build_category_expense_details(
    transactions: list[object],
    categories: list[object],
) -> dict[str, list[CategoryExpenseDetail]]:
    category_by_id = {category.id: category for category in categories}  # type: ignore[attr-defined]
    details: dict[str, list[CategoryExpenseDetail]] = {}
    for tx in transactions:
        if tx.type != TransactionType.EXPENSE:  # type: ignore[attr-defined]
            continue
        categorized_items = [item for item in tx.items if item.category_id is not None]  # type: ignore[attr-defined]
        if categorized_items:
            for item in categorized_items:
                key = str(item.category_id)
                category = category_by_id.get(item.category_id)
                details.setdefault(key, []).append(
                    CategoryExpenseDetail(
                        id=item.id,
                        target="item",
                        name=item.name,
                        amount=money(item.total_amount),
                        transaction_date=tx.transaction_date,  # type: ignore[attr-defined]
                        category_code=category.code if category else "",
                    )
                )
            continue
        if tx.category_id is None:  # type: ignore[attr-defined]
            continue
        key = str(tx.category_id)  # type: ignore[attr-defined]
        category = category_by_id.get(tx.category_id)  # type: ignore[attr-defined]
        name = tx.merchant or tx.description or "Операция"  # type: ignore[attr-defined]
        details.setdefault(key, []).append(
            CategoryExpenseDetail(
                id=tx.id,  # type: ignore[attr-defined]
                target="transaction",
                name=str(name),
                amount=money(tx.amount),  # type: ignore[attr-defined]
                transaction_date=tx.transaction_date,  # type: ignore[attr-defined]
                category_code=category.code if category else "",
            )
        )

    for items in details.values():
        items.sort(key=lambda item: item.transaction_date, reverse=True)
    return details


def render_category_cards(
    categories: list[object],
    details_by_category: dict[str, list[CategoryExpenseDetail]],
    category_options: list[DashboardCategoryOption],
) -> str:
    visible = [category for category in categories if category.spent > 0 or category.monthly_limit]  # type: ignore[attr-defined]
    visible.sort(key=lambda category: category.spent, reverse=True)  # type: ignore[attr-defined]
    if not visible:
        return '<div class="muted">Пока нет подтверждённых расходов по категориям.</div>'
    total_spent = money(sum((category.spent for category in visible), Decimal("0")))  # type: ignore[attr-defined]
    cards = []
    for category in visible[:12]:
        spent = category.spent  # type: ignore[attr-defined]
        limit = category.monthly_limit  # type: ignore[attr-defined]
        remaining = max(Decimal("0"), money(limit - spent)) if limit else None
        pct = percent(spent, limit) if limit else 0
        share_pct = percent(spent, total_spent)
        limit_text = format_money(limit) if limit else "не установлен"
        remaining_text = format_money(remaining) if remaining is not None else "—"
        category_key = str(category.category_id) if category.category_id else ""  # type: ignore[attr-defined]
        detail_rows = render_category_detail_rows(
            details_by_category.get(category_key, []),
            category_options,
        )
        cards.append(
            f"""
            <details class="mini-card">
              <summary class="mini-summary">
                <div class="mini-title">{escape(category.name)}</div>
                <div class="mini-line"><span>Потрачено</span><strong>{format_money(spent)}</strong></div>
                <div class="mini-line"><span>Доля расходов</span><strong>{share_pct}%</strong></div>
                <div class="mini-line"><span>Лимит</span><strong>{limit_text}</strong></div>
                <div class="mini-line"><span>Осталось</span><strong>{remaining_text}</strong></div>
                <div class="bar"><div class="fill {'warn' if pct >= 90 else ''}" style="width:{pct or share_pct}%"></div></div>
              </summary>
              {detail_rows}
            </details>
            """
        )
    return f'<div class="cards-grid">{"".join(cards)}</div>'


def render_category_detail_rows(
    items: list[CategoryExpenseDetail],
    category_options: list[DashboardCategoryOption],
) -> str:
    if not items:
        return '<div class="detail-list"><div class="muted">Покупки по категории не найдены.</div></div>'
    rows = []
    for item in items:
        rows.append(
            f"""
            <div class="detail-row">
              <div>
                <div class="detail-name">{escape(item.name)}</div>
                <div class="detail-date">{format_date(item.transaction_date)}</div>
                {render_category_select(item, category_options)}
                <div class="detail-error"></div>
              </div>
              <div class="detail-amount">{format_money(item.amount)}</div>
            </div>
            """
        )
    return f'<div class="detail-list">{"".join(rows)}</div>'


def render_category_select(
    item: CategoryExpenseDetail,
    category_options: list[DashboardCategoryOption],
) -> str:
    options = []
    for category in category_options:
        selected = " selected" if category.code == item.category_code else ""
        options.append(
            f'<option value="{escape(category.code)}"{selected}>{escape(category.name)}</option>'
        )
    return (
        f'<select class="category-select" data-category-editor data-target="{escape(item.target)}" '
        f'data-id="{item.id}">'
        f'{"".join(options)}'
        "</select>"
    )


def future_payments_total(payments: list[object], today: date) -> Decimal:
    return money(
        sum(
            (
                payment.amount
                for payment in payments
                if payment.payment_date is None or payment.payment_date >= today  # type: ignore[attr-defined]
            ),
            Decimal("0"),
        )
    )


def spending_tempo_text(cycle_elapsed_pct: int, free_spent_pct: int) -> str:
    if free_spent_pct <= cycle_elapsed_pct + 10:
        return "Темп расходов в норме"
    if free_spent_pct <= cycle_elapsed_pct + 25:
        return "Близко к лимиту"
    return "Выше лимита"


def render_donut(
    title: str,
    used: Decimal,
    remaining: Decimal,
    used_label: str,
    remaining_label: str,
    key: str = "",
) -> str:
    total = money(used + remaining)
    pct = percent(used, total)
    donut_attr = f' data-donut="{escape(key)}"' if key else ""
    used_attr = f' data-test="{escape(key)}-used"' if key else ""
    remaining_attr = f' data-test="{escape(key)}-remaining"' if key else ""
    return f"""
      <div class="card donut-card">
        <div class="donut" style="--pct:{pct}%"{donut_attr}></div>
        <div>
          <h2>{escape(title)}</h2>
          <div class="legend">
            <div class="legend-row">
              <span class="swatch"></span>
              <span>{escape(used_label)}</span>
              <strong{used_attr}>{format_money(used)}</strong>
            </div>
            <div class="legend-row">
              <span class="swatch rest"></span>
              <span>{escape(remaining_label)}</span>
              <strong{remaining_attr}>{format_money(remaining)}</strong>
            </div>
          </div>
        </div>
      </div>
    """


def render_transaction_rows(transactions: list[object]) -> str:
    if not transactions:
        return '<div class="muted">Нет операций.</div>'
    rows = []
    for tx in transactions:
        title = tx.merchant or tx.description or tx.type  # type: ignore[attr-defined]
        rows.append(
            f'<div class="row"><div class="name">{escape(str(title))}<div class="muted">{format_date(tx.transaction_date)}</div></div><div class="amount">{format_money(tx.amount)}</div></div>'  # type: ignore[attr-defined]
        )
    return "\n".join(rows)


def clean_payment_name(name: str) -> str:
    parts = name.split()
    while parts and is_payment_metadata_token(parts[-1]):
        parts.pop()
    return " ".join(parts).strip() or name


def is_payment_metadata_token(value: str) -> bool:
    normalized = value.strip().lower().replace(",", ".")
    category_codes = {
        "housing",
        "utilities",
        "groceries",
        "restaurants",
        "transport",
        "child",
        "health",
        "clothing",
        "household",
        "entertainment",
        "subscriptions",
        "gifts",
        "debt",
        "savings",
        "personal_husband",
        "personal_wife",
        "other",
    }
    if normalized in category_codes or normalized in {"€", "eur", "euro", "евро"}:
        return True
    if is_decimal_text(normalized):
        return True
    if is_date_text(normalized):
        return True
    return False


def is_decimal_text(value: str) -> bool:
    try:
        Decimal(value)
    except Exception:
        return False
    return True


def is_date_text(value: str) -> bool:
    chunks = value.replace("-", ".").split(".")
    return len(chunks) == 3 and all(chunk.isdigit() for chunk in chunks)


def percent(value: Decimal, total: Decimal | None) -> int:
    if total is None or total <= 0:
        return 0
    return max(0, min(100, int((money(value) / money(total)) * 100)))


def format_money(value: Decimal) -> str:
    return f"{money(value):,.2f} €".replace(",", " ").replace(".", ",")


def decimal_for_input(value: Decimal) -> str:
    return str(money(value))


def format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def format_date_short(value: date) -> str:
    return value.strftime("%d.%m")
