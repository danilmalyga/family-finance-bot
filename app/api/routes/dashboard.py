from datetime import date
from decimal import Decimal
from html import escape
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_family_id, session_dep
from app.config import Settings, get_settings
from app.domain.enums import TransactionStatus
from app.repositories.transactions import TransactionRepository
from app.services.budget_engine import BudgetEngine
from app.utils.money import money

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    key: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> HTMLResponse:
    expected = settings.api_secret_key.get_secret_value() if settings.api_secret_key else ""
    if expected and key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dashboard key")

    snapshot = await BudgetEngine(session).get_snapshot(family_id, date.today())
    transactions = await TransactionRepository(session).list_for_family(family_id, limit=10)
    confirmed = [tx for tx in transactions if tx.status == TransactionStatus.CONFIRMED]
    draft = [tx for tx in transactions if tx.status == TransactionStatus.DRAFT]
    html = render_dashboard(snapshot=snapshot, confirmed=confirmed, draft=draft)
    return HTMLResponse(html)


def render_dashboard(snapshot: object, confirmed: list[object], draft: list[object]) -> str:
    category_rows = render_category_rows(snapshot.category_summaries)  # type: ignore[attr-defined]
    upcoming_rows = render_upcoming_rows(snapshot.upcoming_payments)  # type: ignore[attr-defined]
    confirmed_rows = render_transaction_rows(confirmed)
    draft_rows = render_transaction_rows(draft)
    planned_balance = snapshot.cycle_balance_after_plan  # type: ignore[attr-defined]
    mandatory_pct = percent(snapshot.mandatory_remaining, snapshot.total_income)  # type: ignore[attr-defined]
    available_pct = percent(max(Decimal("0"), snapshot.available_to_spend), snapshot.total_income)  # type: ignore[attr-defined]
    reserve_pct = percent(snapshot.current_reserve, snapshot.minimum_reserve)  # type: ignore[attr-defined]
    groceries_donut = render_groceries_donut(snapshot.groceries_week)  # type: ignore[attr-defined]
    period_spent = (  # type: ignore[attr-defined]
        snapshot.discretionary_spent
        + snapshot.mandatory_remaining
        + snapshot.groceries_cycle_reserved
        + snapshot.total_savings
    )
    period_donut = render_donut(
        "Период от зарплаты",
        period_spent,
        max(Decimal("0"), snapshot.available_to_spend),  # type: ignore[attr-defined]
        "использовано",
        "остаток",
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Family Finance Dashboard</title>
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
      grid-template-columns: repeat(4, minmax(0, 1fr));
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
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
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
    @media (max-width: 900px) {{
      .kpis, .grid, .two, .donuts {{ grid-template-columns: 1fr; }}
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
    <div class="period">Период: {format_date(snapshot.period_start)} — {format_date(snapshot.period_end)}</div>
  </header>
  <main>
    <section class="kpis">
      {kpi("Реальный остаток", planned_balance)}
      {kpi("Доступно к тратам", snapshot.available_to_spend, "good" if snapshot.available_to_spend >= 0 else "bad")}
      {kpi("Расходы периода", snapshot.total_expenses, "warn")}
      {kpi("Обычные траты", snapshot.discretionary_spent, "warn")}
      {kpi("Лимит в день", snapshot.safe_daily_limit, "blue")}
    </section>

    <section class="donuts">
      {groceries_donut}
      {period_donut}
    </section>

    <section class="grid">
      <div class="card">
        <h2>Состояние бюджета</h2>
        {metric("Доступно после обязательных платежей, накоплений и резерва", snapshot.available_to_spend, available_pct, "good")}
        {metric("Обязательные платежи периода", snapshot.mandatory_remaining, mandatory_pct, "warn")}
        {metric("Резерв", snapshot.current_reserve, reserve_pct, "blue", suffix=f"из {format_money(snapshot.minimum_reserve)}")}
        <div class="row"><div class="name muted">Фактический баланс операций</div><div class="amount">{format_money(snapshot.balance)}</div></div>
        <div class="row"><div class="name muted">Резерв продуктов цикла</div><div class="amount">{format_money(snapshot.groceries_cycle_reserved)}</div></div>
        <div class="row"><div class="name muted">Остаток цели накоплений</div><div class="amount">{format_money(snapshot.savings_target_remaining)}</div></div>
        <div class="row"><div class="name muted">Недобор резерва</div><div class="amount">{format_money(snapshot.reserve_gap)}</div></div>
        <div class="row"><div class="name muted">До следующего дохода</div><div class="amount">{snapshot.days_until_next_income} дн.</div></div>
      </div>

      <div class="card">
        <h2>Обязательные платежи периода</h2>
        {upcoming_rows}
      </div>
    </section>

    <section class="card">
      <h2>Категории</h2>
      {category_rows}
    </section>

    <section class="two">
      <div class="card">
        <h2>Последние подтверждённые операции</h2>
        {confirmed_rows}
      </div>
      <div class="card">
        <h2>Черновики к подтверждению</h2>
        {draft_rows}
      </div>
    </section>
  </main>
</body>
</html>"""


def kpi(label: str, value: Decimal, tone: str = "") -> str:
    return f"""
      <div class="card">
        <div class="label">{escape(label)}</div>
        <div class="value {tone}">{format_money(value)}</div>
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


def render_groceries_donut(groceries_week: object | None) -> str:
    if groceries_week is None:
        return """
          <div class="card">
            <h2>Бюджет продуктов на неделю</h2>
            <div class="muted">Недельный лимит продуктов не настроен.</div>
          </div>
        """
    title = (
        "Бюджет продуктов на неделю "
        f"{format_date(groceries_week.week_start)} — {format_date(groceries_week.week_end)}"  # type: ignore[attr-defined]
    )
    return render_donut(
        title,
        groceries_week.spent,  # type: ignore[attr-defined]
        groceries_week.remaining,  # type: ignore[attr-defined]
        "потрачено",
        "осталось",
    )


def render_donut(
    title: str,
    used: Decimal,
    remaining: Decimal,
    used_label: str,
    remaining_label: str,
) -> str:
    total = money(used + remaining)
    pct = percent(used, total)
    return f"""
      <div class="card donut-card">
        <div class="donut" style="--pct:{pct}%"></div>
        <div>
          <h2>{escape(title)}</h2>
          <div class="legend">
            <div class="legend-row">
              <span class="swatch"></span>
              <span>{escape(used_label)}</span>
              <strong>{format_money(used)}</strong>
            </div>
            <div class="legend-row">
              <span class="swatch rest"></span>
              <span>{escape(remaining_label)}</span>
              <strong>{format_money(remaining)}</strong>
            </div>
          </div>
        </div>
      </div>
    """


def render_category_rows(categories: list[object]) -> str:
    visible = [category for category in categories if category.spent > 0 or category.monthly_limit]  # type: ignore[attr-defined]
    visible.sort(key=lambda category: category.spent, reverse=True)  # type: ignore[attr-defined]
    if not visible:
        return '<div class="muted">Пока нет подтверждённых расходов по категориям.</div>'
    rows = []
    for category in visible[:12]:
        limit = category.monthly_limit  # type: ignore[attr-defined]
        spent = category.spent  # type: ignore[attr-defined]
        pct = percent(spent, limit) if limit else 0
        limit_text = f" / {format_money(limit)}" if limit else ""
        rows.append(
            f"""
            <div class="metric">
              <div class="row">
                <div class="name">{escape(category.name)}</div>
                <div class="amount">{format_money(spent)}{limit_text}</div>
              </div>
              <div class="bar"><div class="fill {'warn' if pct >= 90 else ''}" style="width:{pct}%"></div></div>
            </div>
            """
        )
    return "\n".join(rows)


def render_upcoming_rows(payments: list[object]) -> str:
    if not payments:
        return '<div class="muted">До конца периода обязательных платежей не найдено.</div>'
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


def render_transaction_rows(transactions: list[object]) -> str:
    if not transactions:
        return '<div class="muted">Нет операций.</div>'
    rows = []
    for tx in transactions:
        title = tx.merchant or tx.description or tx.type  # type: ignore[attr-defined]
        rows.append(
            f'<div class="row"><div class="name">{escape(title)}<div class="muted">{format_date(tx.transaction_date)}</div></div><div class="amount">{format_money(tx.amount)}</div></div>'  # type: ignore[attr-defined]
        )
    return "\n".join(rows)


def clean_payment_name(name: str) -> str:
    parts = name.split()
    if len(parts) < 4:
        return name
    amount_part = parts[-3].replace(",", ".")
    day_part = parts[-2]
    if is_decimal_text(amount_part) and day_part.isdigit():
        return " ".join(parts[:-3]) or name
    return name


def is_decimal_text(value: str) -> bool:
    try:
        Decimal(value)
    except Exception:
        return False
    return True


def percent(value: Decimal, total: Decimal | None) -> int:
    if total is None or total <= 0:
        return 0
    return max(0, min(100, int((money(value) / money(total)) * 100)))


def format_money(value: Decimal) -> str:
    return f"{money(value):,.2f} €".replace(",", " ").replace(".", ",")


def format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")
